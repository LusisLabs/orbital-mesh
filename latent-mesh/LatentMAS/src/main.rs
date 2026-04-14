use anyhow::Result;
use clap::Parser;

use latentmas::run::{run, Cli};

fn main() -> Result<()> {
    run(Cli::parse())
}
