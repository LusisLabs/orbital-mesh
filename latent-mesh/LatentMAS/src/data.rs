use std::{
    fs::File,
    io::{BufRead, BufReader, Read},
    path::Path,
};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::eval::{extract_gold, normalize_answer};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Example {
    pub question: String,
    pub solution: String,
    pub gold: String,
}

pub fn load_examples(path: impl AsRef<Path>) -> Result<Vec<Example>> {
    let path = path.as_ref();
    let file = File::open(path).with_context(|| format!("failed to open {}", path.display()))?;
    let extension = path.extension().and_then(|value| value.to_str());
    match extension {
        Some("jsonl") => load_jsonl(file),
        Some("json") => load_json(file),
        _ => anyhow::bail!("unsupported dataset format for {}", path.display()),
    }
}

fn load_jsonl(file: File) -> Result<Vec<Example>> {
    let mut examples = Vec::new();
    for (line_number, line) in BufReader::new(file).lines().enumerate() {
        let line =
            line.with_context(|| format!("failed to read jsonl line {}", line_number + 1))?;
        if line.trim().is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(&line)
            .with_context(|| format!("invalid jsonl line {}", line_number + 1))?;
        examples.push(example_from_value(&value)?);
    }
    Ok(examples)
}

fn load_json(mut file: File) -> Result<Vec<Example>> {
    let mut content = String::new();
    file.read_to_string(&mut content)
        .context("failed to read json dataset")?;
    let value: Value = serde_json::from_str(&content).context("invalid json dataset")?;
    match value {
        Value::Array(items) => items.iter().map(example_from_value).collect(),
        other => Ok(vec![example_from_value(&other)?]),
    }
}

fn example_from_value(value: &Value) -> Result<Example> {
    let question = first_string(value, &["question", "query", "problem", "prompt"])
        .context("example is missing question/query/problem/prompt")?;
    let solution = first_string(value, &["solution", "answer", "gold", "test"]).unwrap_or_default();
    let gold = first_string(value, &["gold"])
        .or_else(|| normalize_answer(extract_gold(&solution).as_deref()))
        .or_else(|| normalize_answer(Some(&solution)))
        .unwrap_or_default();

    Ok(Example {
        question,
        solution,
        gold,
    })
}

fn first_string(value: &Value, keys: &[&str]) -> Option<String> {
    keys.iter()
        .filter_map(|key| value.get(*key))
        .find_map(|field| match field {
            Value::String(text) => Some(text.trim().to_string()),
            Value::Number(number) => Some(number.to_string()),
            _ => None,
        })
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use tempfile::NamedTempFile;

    use super::*;

    #[test]
    fn loads_jsonl_examples() {
        let mut file = NamedTempFile::with_suffix(".jsonl").unwrap();
        writeln!(
            file,
            r#"{{"question":"q","solution":"work #### 7","gold":"7"}}"#
        )
        .unwrap();
        let examples = load_examples(file.path()).unwrap();
        assert_eq!(examples[0].gold, "7");
    }
}
