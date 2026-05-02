use std::path::Path;

use sentencepiece::SentencePieceProcessor;
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokenizers::Tokenizer;

use crate::context::{estimate_tokens, ContextWindow, RetentionSide};

#[derive(Debug, Error)]
pub enum MeshTokenizerError {
    #[error("failed to load Hugging Face tokenizer from {path}: {source}")]
    HuggingFaceLoad {
        path: String,
        source: tokenizers::Error,
    },
    #[error("failed to load SentencePiece model from {path}: {source}")]
    SentencePieceLoad {
        path: String,
        source: sentencepiece::SentencePieceError,
    },
    #[error("failed to tokenize text with Hugging Face tokenizer: {0}")]
    HuggingFaceTokenize(tokenizers::Error),
    #[error("failed to tokenize text with SentencePiece model: {0}")]
    SentencePieceTokenize(sentencepiece::SentencePieceError),
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum TokenizerBackend {
    Heuristic,
    HuggingFace,
    SentencePiece,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TokenizedText {
    pub backend: TokenizerBackend,
    pub token_count: usize,
}

pub enum MeshTokenizer {
    Heuristic,
    HuggingFace(Box<Tokenizer>),
    SentencePiece(SentencePieceProcessor),
}

impl MeshTokenizer {
    pub fn heuristic() -> Self {
        Self::Heuristic
    }

    pub fn from_huggingface_file(path: impl AsRef<Path>) -> Result<Self, MeshTokenizerError> {
        let path = path.as_ref();
        Tokenizer::from_file(path)
            .map(Box::new)
            .map(Self::HuggingFace)
            .map_err(|source| MeshTokenizerError::HuggingFaceLoad {
                path: path.display().to_string(),
                source,
            })
    }

    pub fn from_sentencepiece_file(path: impl AsRef<Path>) -> Result<Self, MeshTokenizerError> {
        let path = path.as_ref();
        SentencePieceProcessor::open(path)
            .map(Self::SentencePiece)
            .map_err(|source| MeshTokenizerError::SentencePieceLoad {
                path: path.display().to_string(),
                source,
            })
    }

    pub fn backend(&self) -> TokenizerBackend {
        match self {
            Self::Heuristic => TokenizerBackend::Heuristic,
            Self::HuggingFace(_) => TokenizerBackend::HuggingFace,
            Self::SentencePiece(_) => TokenizerBackend::SentencePiece,
        }
    }

    pub fn tokenize(&self, text: &str) -> Result<TokenizedText, MeshTokenizerError> {
        let token_count = match self {
            Self::Heuristic => estimate_tokens(text),
            Self::HuggingFace(tokenizer) => tokenizer
                .encode(text, false)
                .map_err(MeshTokenizerError::HuggingFaceTokenize)?
                .len(),
            Self::SentencePiece(processor) => processor
                .encode(text)
                .map_err(MeshTokenizerError::SentencePieceTokenize)?
                .len(),
        };
        Ok(TokenizedText {
            backend: self.backend(),
            token_count,
        })
    }

    pub fn count_tokens(&self, text: &str) -> Result<usize, MeshTokenizerError> {
        self.tokenize(text).map(|tokens| tokens.token_count)
    }

    pub fn trim_to_token_budget(
        &self,
        text: &str,
        max_tokens: Option<usize>,
        side: RetentionSide,
    ) -> Result<ContextWindow, MeshTokenizerError> {
        let original_chars = text.chars().count();
        let Some(max_tokens) = max_tokens else {
            return Ok(ContextWindow {
                text: text.to_string(),
                original_chars,
                retained_chars: original_chars,
                estimated_tokens: self.count_tokens(text)?,
                truncated: false,
            });
        };
        if max_tokens == 0 {
            return Ok(ContextWindow {
                text: String::new(),
                original_chars,
                retained_chars: 0,
                estimated_tokens: 0,
                truncated: original_chars > 0,
            });
        }

        if self.count_tokens(text)? <= max_tokens {
            return Ok(ContextWindow {
                text: text.to_string(),
                original_chars,
                retained_chars: original_chars,
                estimated_tokens: self.count_tokens(text)?,
                truncated: false,
            });
        }

        let char_boundaries = char_boundaries(text);
        let mut low = 0usize;
        let mut high = original_chars;
        while low < high {
            let mid = (low + high).div_ceil(2);
            let candidate = slice_by_retained_chars(text, &char_boundaries, mid, side);
            if self.count_tokens(candidate)? <= max_tokens {
                low = mid;
            } else {
                high = mid - 1;
            }
        }

        let retained = slice_by_retained_chars(text, &char_boundaries, low, side).to_string();
        Ok(ContextWindow {
            estimated_tokens: self.count_tokens(&retained)?,
            retained_chars: retained.chars().count(),
            text: retained,
            original_chars,
            truncated: true,
        })
    }
}

fn char_boundaries(text: &str) -> Vec<usize> {
    let mut boundaries: Vec<usize> = text.char_indices().map(|(idx, _)| idx).collect();
    boundaries.push(text.len());
    boundaries
}

fn slice_by_retained_chars<'a>(
    text: &'a str,
    char_boundaries: &[usize],
    retained_chars: usize,
    side: RetentionSide,
) -> &'a str {
    match side {
        RetentionSide::Head => &text[..char_boundaries[retained_chars]],
        RetentionSide::Tail => {
            let start_char = char_boundaries.len() - 1 - retained_chars;
            &text[char_boundaries[start_char]..]
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokenizers::models::wordlevel::WordLevel;
    use tokenizers::pre_tokenizers::whitespace::Whitespace;

    #[test]
    fn heuristic_count_matches_legacy_estimate() {
        let tokenizer = MeshTokenizer::heuristic();
        assert_eq!(tokenizer.count_tokens("abcdefgh").unwrap(), 2);
    }

    #[test]
    fn trims_head_on_character_boundaries() {
        let tokenizer = MeshTokenizer::heuristic();
        let window = tokenizer
            .trim_to_token_budget("alpha beta gamma", Some(2), RetentionSide::Head)
            .unwrap();
        assert_eq!(window.text, "alpha be");
        assert!(window.truncated);
    }

    #[test]
    fn trims_tail_on_character_boundaries() {
        let tokenizer = MeshTokenizer::heuristic();
        let window = tokenizer
            .trim_to_token_budget("alpha beta gamma", Some(2), RetentionSide::Tail)
            .unwrap();
        assert_eq!(window.text, "ta gamma");
        assert!(window.truncated);
    }

    #[test]
    fn keeps_utf8_valid_after_tail_trim() {
        let tokenizer = MeshTokenizer::heuristic();
        let window = tokenizer
            .trim_to_token_budget("alpha beta gamma delta", Some(2), RetentionSide::Tail)
            .unwrap();
        assert!(window.text.is_char_boundary(0));
        assert!(window.text.is_char_boundary(window.text.len()));
    }

    #[test]
    fn loads_huggingface_tokenizer_json() {
        let dir = tempfile::tempdir().unwrap();
        let vocab_path = dir.path().join("vocab.json");
        std::fs::write(&vocab_path, r#"{"<unk>":0,"alpha":1,"beta":2,"gamma":3}"#).unwrap();

        let model =
            WordLevel::from_file(vocab_path.to_str().unwrap(), "<unk>".to_string()).unwrap();
        let mut hf_tokenizer = Tokenizer::new(model);
        hf_tokenizer.with_pre_tokenizer(Some(Whitespace));

        let tokenizer_path = dir.path().join("tokenizer.json");
        hf_tokenizer.save(&tokenizer_path, false).unwrap();

        let tokenizer = MeshTokenizer::from_huggingface_file(&tokenizer_path).unwrap();
        assert_eq!(tokenizer.backend(), TokenizerBackend::HuggingFace);
        assert_eq!(tokenizer.count_tokens("alpha beta gamma").unwrap(), 3);
    }
}
