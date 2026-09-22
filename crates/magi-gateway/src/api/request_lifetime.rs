//! Propagate caller cancellation only to handlers whose work is cancellable.

use tokio::sync::watch;

#[derive(Clone)]
pub(super) struct ReadCancellation(watch::Receiver<bool>);

pub(super) struct ReadCaller(watch::Sender<bool>);

impl ReadCancellation {
    pub(super) fn channel() -> (ReadCaller, Self) {
        let (sender, receiver) = watch::channel(false);
        (ReadCaller(sender), Self(receiver))
    }

    pub(super) async fn cancelled(&self) {
        let mut receiver = self.0.clone();
        if !*receiver.borrow_and_update() {
            let _ = receiver.changed().await;
        }
    }
}

impl Drop for ReadCaller {
    fn drop(&mut self) {
        self.0.send_replace(true);
    }
}
