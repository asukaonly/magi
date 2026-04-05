use axum::body::Body;
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;

pub type HttpClient = Client<HttpConnector, Body>;

#[derive(Clone)]
pub struct ApiState {
    pub python_api_port: u16,
    pub client: HttpClient,
}
