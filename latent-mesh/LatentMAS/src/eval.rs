use regex::Regex;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum TaskKind {
    Numeric,
    MultipleChoice,
    Code,
}

pub fn task_kind(task: &str) -> TaskKind {
    match task {
        "mbppplus" | "humanevalplus" => TaskKind::Code,
        "arc_easy" | "arc_challenge" | "gpqa" | "medqa" | "winogrande" => TaskKind::MultipleChoice,
        _ => TaskKind::Numeric,
    }
}

pub fn normalize_answer(answer: Option<&str>) -> Option<String> {
    answer.map(|value| value.trim().to_ascii_lowercase())
}

pub fn extract_gold(text: &str) -> Option<String> {
    let re = Regex::new(r"####\s*([-+]?\d+(?:\.\d+)?)").expect("valid gold regex");
    re.captures(text)
        .and_then(|captures| captures.get(1))
        .map(|value| value.as_str().to_string())
}

pub fn extract_boxed_or_last_number(text: &str) -> Option<String> {
    let boxed = Regex::new(r"\\boxed\{([^}]*)\}").expect("valid boxed regex");
    if let Some(captures) = boxed.captures_iter(text).last() {
        let content = captures.get(1)?.as_str();
        let number = Regex::new(r"[-+]?\d+(?:\.\d+)?").expect("valid number regex");
        return number
            .find(content)
            .map(|matched| matched.as_str().to_string())
            .or_else(|| Some(content.trim().to_string()));
    }

    let number = Regex::new(r"[-+]?\d+(?:\.\d+)?").expect("valid number regex");
    number
        .find_iter(text)
        .last()
        .map(|matched| matched.as_str().to_string())
}

pub fn extract_markdown_python_block(text: &str) -> Option<String> {
    let re = Regex::new(r"(?is)```python(.*?)```").expect("valid python block regex");
    re.captures_iter(text)
        .last()
        .and_then(|captures| captures.get(1))
        .map(|value| value.as_str().trim().to_string())
}

pub fn is_correct(task: &str, prediction_text: &str, gold: &str) -> bool {
    match task_kind(task) {
        TaskKind::Code => extract_markdown_python_block(prediction_text).is_some(),
        TaskKind::Numeric | TaskKind::MultipleChoice => {
            let pred = normalize_answer(extract_boxed_or_last_number(prediction_text).as_deref());
            let gold = normalize_answer(Some(gold));
            pred.is_some() && pred == gold
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_boxed_answer_before_falling_back_to_number() {
        assert_eq!(
            extract_boxed_or_last_number("work 12 then \\boxed{A}").as_deref(),
            Some("A")
        );
        assert_eq!(
            extract_boxed_or_last_number("work 12 then 42").as_deref(),
            Some("42")
        );
    }

    #[test]
    fn extracts_python_block_case_insensitively() {
        assert_eq!(
            extract_markdown_python_block("```Python\nprint(1)\n```").as_deref(),
            Some("print(1)")
        );
    }
}
