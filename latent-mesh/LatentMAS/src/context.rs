use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RetentionSide {
    Head,
    Tail,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContextWindow {
    pub text: String,
    pub original_chars: usize,
    pub retained_chars: usize,
    #[serde(alias = "token_count")]
    pub estimated_tokens: usize,
    pub truncated: bool,
}

pub fn estimate_tokens(text: &str) -> usize {
    let chars = text.chars().count();
    if chars == 0 {
        0
    } else {
        chars.div_ceil(4)
    }
}

pub fn trim_to_estimated_token_budget(
    text: &str,
    max_tokens: Option<usize>,
    side: RetentionSide,
) -> ContextWindow {
    let original_chars = text.chars().count();
    let Some(max_tokens) = max_tokens else {
        return ContextWindow {
            text: text.to_string(),
            original_chars,
            retained_chars: original_chars,
            estimated_tokens: estimate_tokens(text),
            truncated: false,
        };
    };

    let max_chars = max_tokens.saturating_mul(4);
    if original_chars <= max_chars {
        return ContextWindow {
            text: text.to_string(),
            original_chars,
            retained_chars: original_chars,
            estimated_tokens: estimate_tokens(text),
            truncated: false,
        };
    }

    let text: String = match side {
        RetentionSide::Head => text.chars().take(max_chars).collect(),
        RetentionSide::Tail => {
            let start = original_chars.saturating_sub(max_chars);
            text.chars().skip(start).collect()
        }
    };
    ContextWindow {
        estimated_tokens: estimate_tokens(&text),
        retained_chars: text.chars().count(),
        text,
        original_chars,
        truncated: true,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn retains_tail_under_budget() {
        let window = trim_to_estimated_token_budget("abcdefghij", Some(1), RetentionSide::Tail);
        assert_eq!(window.text, "ghij");
        assert!(window.truncated);
    }

    #[test]
    fn none_budget_keeps_context() {
        let window = trim_to_estimated_token_budget("abcdef", None, RetentionSide::Tail);
        assert_eq!(window.text, "abcdef");
        assert!(!window.truncated);
    }
}
