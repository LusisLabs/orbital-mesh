use serde::{Deserialize, Serialize};

use crate::agents::AgentRole;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PromptMode {
    Sequential,
    Hierarchical,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessage {
    pub role: String,
    pub content: String,
}

pub fn build_prompt(
    mode: PromptMode,
    role: AgentRole,
    task: &str,
    question: &str,
    context: &str,
    latent: bool,
) -> Vec<ChatMessage> {
    let system = ChatMessage {
        role: "system".to_string(),
        content: "You are Qwen, created by Alibaba Cloud. You are a helpful assistant.".to_string(),
    };
    let content = match (mode, latent, role) {
        (PromptMode::Sequential, true, AgentRole::Planner) => format!(
            "You are a Planner Agent. Given an input question, design a clear, step-by-step plan for how to solve the question.\n\nQuestion: {question}\n\nYour outlined plan should be concise with a few bulletpoints for each step. Do not produce the final answer."
        ),
        (PromptMode::Sequential, true, AgentRole::Critic) => format!(
            "Question: {question}\n\nYou are a Critic Agent. Review the latent plan and provide the original plan contents plus constructive feedback."
        ),
        (PromptMode::Sequential, true, AgentRole::Refiner) => format!(
            "Question: {question}\n\nYou are a Refiner Agent. Use the latent prior plan and feedback to write a refined plan."
        ),
        (_, _, AgentRole::Judger) => judger_prompt(task, question, context, latent),
        (PromptMode::Hierarchical, _, AgentRole::Planner) => role_prompt("math agent", task, question, context),
        (PromptMode::Hierarchical, _, AgentRole::Critic) => role_prompt("science agent", task, question, context),
        (PromptMode::Hierarchical, _, AgentRole::Refiner) => role_prompt("code agent", task, question, context),
        (PromptMode::Sequential, false, AgentRole::Planner) => role_prompt("Planner Agent", task, question, context),
        (PromptMode::Sequential, false, AgentRole::Critic) => role_prompt("Critic Agent", task, question, context),
        (PromptMode::Sequential, false, AgentRole::Refiner) => role_prompt("Refiner Agent", task, question, context),
    };

    vec![
        system,
        ChatMessage {
            role: "user".to_string(),
            content,
        },
    ]
}

fn role_prompt(role_name: &str, task: &str, question: &str, context: &str) -> String {
    let answer_rule = answer_rule(task);
    let context_block = if context.trim().is_empty() {
        String::new()
    } else {
        format!("\n\nPrior agent context:\n{context}")
    };
    format!(
        "You are a {role_name}. Given the input question, reason step-by-step. {answer_rule}\n\nInput Question: {question}{context_block}\n\nYour response:"
    )
}

fn judger_prompt(task: &str, question: &str, context: &str, latent: bool) -> String {
    let reference = if latent {
        "You are provided with latent information for reference."
    } else if context.trim().is_empty() {
        "No prior agent context is available."
    } else {
        "You are provided with prior agent responses for reference."
    };
    format!(
        "Target Question: {question}\n\n{reference}\n\nThe reference may contain irrelevant content. Ignore it if it is not useful.\n\nYou must reason step-by-step. {}",
        answer_rule(task)
    )
}

fn answer_rule(task: &str) -> &'static str {
    match task {
        "arc_easy" | "arc_challenge" | "gpqa" | "medqa" => {
            "Put the final answer inside \\boxed{YOUR_FINAL_ANSWER}; choose only A, B, C, or D."
        }
        "winogrande" => {
            "Put the final answer inside \\boxed{YOUR_FINAL_ANSWER}; choose only 1 or 2."
        }
        "mbppplus" | "humanevalplus" => {
            "Return only a self-contained Python solution inside a markdown ```python code block."
        }
        _ => "Put the final answer inside \\boxed{YOUR_FINAL_ANSWER}.",
    }
}
