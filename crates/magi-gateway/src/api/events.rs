use std::convert::Infallible;
use std::sync::Arc;
use std::time::Duration;

use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse, Response,
    },
};
use futures_util::stream;
use tokio::sync::broadcast::error::RecvError;

use super::{security::SESSION_TOKEN_HEADER, state::ApiState};

pub async fn subscribe(State(state): State<ApiState>, headers: HeaderMap) -> Response {
    let after = headers
        .get("last-event-id")
        .and_then(|value| value.to_str().ok());
    if after.is_some_and(|id| id.len() > 100) {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let Some(subscription) = state.events.subscribe(after) else {
        return StatusCode::TOO_MANY_REQUESTS.into_response();
    };
    let token = headers
        .get(SESSION_TOKEN_HEADER)
        .and_then(|value| value.to_str().ok())
        .unwrap_or_default()
        .to_owned();
    let auth = Arc::clone(&state.security.auth);
    let hub = Arc::clone(&state.events);
    let stream = stream::unfold(
        (subscription, false),
        move |(mut subscription, finished)| {
            let auth = Arc::clone(&auth);
            let token = token.clone();
            let hub = Arc::clone(&hub);
            async move {
                if finished {
                    return None;
                }
                loop {
                    // Long-lived connections lose authorization when their device or session expires.
                    auth.authenticate(&token)?;
                    if let Some(event) = subscription.replay.pop_front() {
                        let frame = Event::default()
                            .event("magi")
                            .id(&event.envelope.event_id)
                            .data(&event.json);
                        return Some((Ok::<_, Infallible>(frame), (subscription, false)));
                    }
                    match tokio::time::timeout(Duration::from_secs(2), subscription.receiver.recv())
                        .await
                    {
                        Ok(Ok(event)) => subscription.replay.push_back(event),
                        Ok(Err(RecvError::Lagged(_))) => {
                            // Tell the client to rebuild its snapshot, then release the congested stream.
                            let event = hub.resync_hint("subscriber_lagged");
                            let frame = Event::default()
                                .event("magi")
                                .id(&event.envelope.event_id)
                                .data(&event.json);
                            return Some((Ok(frame), (subscription, true)));
                        }
                        Ok(Err(RecvError::Closed)) => return None,
                        Err(_) => {}
                    }
                }
            }
        },
    );
    let mut response = Sse::new(stream)
        .keep_alive(KeepAlive::new().interval(Duration::from_secs(15)))
        .into_response();
    response
        .headers_mut()
        .insert("x-accel-buffering", "no".parse().unwrap());
    response
}
