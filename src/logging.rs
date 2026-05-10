use tracing_subscriber::{fmt, EnvFilter};

pub fn init() {
    let filter = EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info"));
    let builder = fmt().with_env_filter(filter).with_target(false);
    if std::env::var_os("JOURNAL_STREAM").is_some() || std::env::var_os("INVOCATION_ID").is_some() {
        builder.without_time().init();
    } else {
        builder.init();
    }
}
