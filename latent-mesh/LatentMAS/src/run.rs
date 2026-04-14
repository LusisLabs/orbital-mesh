use std::{path::PathBuf, process::Command};

use anyhow::{Context, Result};
use clap::{Parser, ValueEnum};
use serde::Serialize;

use crate::{
    agents::default_agents,
    briefing::plan_task_guided_compaction,
    context::{trim_to_estimated_token_budget, RetentionSide},
    data::load_examples,
    prompts::{build_prompt, PromptMode},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum Method {
    Baseline,
    TextMas,
    LatentMas,
    LatentBriefing,
}

#[derive(Debug, Parser)]
#[command(version, about = "Rust orchestration core for LatentMAS experiments")]
pub struct Cli {
    #[arg(long, value_enum, default_value = "latent-briefing")]
    pub method: Method,
    #[arg(long, default_value = "Qwen/Qwen3-14B")]
    pub model_name: String,
    #[arg(long, default_value = "gsm8k")]
    pub task: String,
    #[arg(long, default_value = "sequential")]
    pub prompt: String,
    #[arg(long)]
    pub dataset: Option<PathBuf>,
    #[arg(long, default_value_t = -1)]
    pub max_samples: isize,
    #[arg(long, default_value_t = 1.0)]
    pub briefing_threshold: f32,
    #[arg(long, default_value_t = 2048)]
    pub context_token_budget: usize,
    #[arg(long)]
    pub python_backend: bool,
    #[arg(last = true)]
    pub backend_args: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct DryRunSummary {
    pub method: String,
    pub task: String,
    pub model_name: String,
    pub examples_loaded: usize,
    pub agents: Vec<&'static str>,
    pub compaction_threshold: f32,
    pub context_token_budget: usize,
    pub sample_prompt_messages: usize,
    pub sample_context_truncated: bool,
}

pub fn run(cli: Cli) -> Result<()> {
    if cli.python_backend {
        return run_python_backend(&cli);
    }

    let examples = match &cli.dataset {
        Some(path) => load_examples(path)?,
        None => Vec::new(),
    };
    let mode = match cli.prompt.as_str() {
        "hierarchical" => PromptMode::Hierarchical,
        _ => PromptMode::Sequential,
    };
    let sample_prompt_messages = examples
        .first()
        .map(|example| {
            let context = trim_to_estimated_token_budget(
                &example.solution,
                Some(cli.context_token_budget),
                RetentionSide::Tail,
            );
            build_prompt(
                mode,
                default_agents()[0].role,
                &cli.task,
                &example.question,
                &context.text,
                matches!(cli.method, Method::LatentMas | Method::LatentBriefing),
            )
            .len()
        })
        .unwrap_or(0);
    let sample_context_truncated = examples
        .first()
        .map(|example| {
            trim_to_estimated_token_budget(
                &example.solution,
                Some(cli.context_token_budget),
                RetentionSide::Tail,
            )
            .truncated
        })
        .unwrap_or(false);

    let _validated_plan =
        plan_task_guided_compaction(&[vec![0.1, 0.3, 0.8]], None, cli.briefing_threshold)
            .context("failed to validate briefing compaction planner")?;

    let summary = DryRunSummary {
        method: format!("{:?}", cli.method),
        task: cli.task,
        model_name: cli.model_name,
        examples_loaded: examples.len(),
        agents: default_agents().iter().map(|agent| agent.name).collect(),
        compaction_threshold: cli.briefing_threshold,
        context_token_budget: cli.context_token_budget,
        sample_prompt_messages,
        sample_context_truncated,
    };
    println!("{}", serde_json::to_string_pretty(&summary)?);
    Ok(())
}

fn run_python_backend(cli: &Cli) -> Result<()> {
    let mut command = Command::new("python");
    command.arg("run.py");
    command.arg("--method").arg(match cli.method {
        Method::Baseline => "baseline",
        Method::TextMas => "text_mas",
        Method::LatentMas | Method::LatentBriefing => "latent_mas",
    });
    command.arg("--model_name").arg(&cli.model_name);
    command.arg("--task").arg(&cli.task);
    command.arg("--prompt").arg(&cli.prompt);
    if cli.max_samples >= 0 {
        command
            .arg("--max_samples")
            .arg(cli.max_samples.to_string());
    }
    command
        .arg("--text_mas_context_tokens")
        .arg(cli.context_token_budget.to_string());
    command.args(&cli.backend_args);

    let status = command.status().context("failed to start python backend")?;
    if !status.success() {
        anyhow::bail!("python backend exited with {status}");
    }
    Ok(())
}
