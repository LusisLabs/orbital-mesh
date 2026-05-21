use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum BriefingError {
    #[error("attention scores must not be empty")]
    EmptyScores,
    #[error(
        "head weights must be empty or match score head count: got {weights}, expected {heads}"
    )]
    HeadWeightMismatch { weights: usize, heads: usize },
    #[error("all attention heads must have the same position count")]
    RaggedScores,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CompactionPlan {
    pub threshold: f32,
    pub median: f32,
    pub mad: f32,
    pub cutoff: f32,
    pub retained_positions: Vec<usize>,
    pub retained_fraction: f32,
}

pub fn plan_task_guided_compaction(
    attention_scores_by_head: &[Vec<f32>],
    head_weights: Option<&[f32]>,
    threshold: f32,
) -> Result<CompactionPlan, BriefingError> {
    if attention_scores_by_head.is_empty() {
        return Err(BriefingError::EmptyScores);
    }
    let positions = attention_scores_by_head[0].len();
    if positions == 0 {
        return Err(BriefingError::EmptyScores);
    }
    if attention_scores_by_head
        .iter()
        .any(|scores| scores.len() != positions)
    {
        return Err(BriefingError::RaggedScores);
    }

    let weights = match head_weights {
        Some(weights) if weights.len() != attention_scores_by_head.len() => {
            return Err(BriefingError::HeadWeightMismatch {
                weights: weights.len(),
                heads: attention_scores_by_head.len(),
            })
        }
        Some(weights) => weights.to_vec(),
        None => vec![1.0; attention_scores_by_head.len()],
    };

    let weight_sum: f32 = weights.iter().copied().sum();
    let divisor = if weight_sum.abs() < f32::EPSILON {
        weights.len() as f32
    } else {
        weight_sum
    };

    let mut position_scores = vec![0.0; positions];
    for (head_scores, weight) in attention_scores_by_head.iter().zip(weights.iter()) {
        for (idx, score) in head_scores.iter().enumerate() {
            position_scores[idx] += score * weight;
        }
    }
    for score in &mut position_scores {
        *score /= divisor;
    }

    let center = median(&position_scores);
    let deviations: Vec<f32> = position_scores
        .iter()
        .map(|score| (score - center).abs())
        .collect();
    let mad = median(&deviations);
    let cutoff = center + threshold * mad;
    let retained_positions: Vec<usize> = position_scores
        .iter()
        .enumerate()
        .filter_map(|(idx, score)| (*score > cutoff).then_some(idx))
        .collect();
    let retained_fraction = retained_positions.len() as f32 / positions as f32;

    Ok(CompactionPlan {
        threshold,
        median: center,
        mad,
        cutoff,
        retained_positions,
        retained_fraction,
    })
}

fn median(values: &[f32]) -> f32 {
    let mut sorted = values.to_vec();
    sorted.sort_by(|left, right| left.total_cmp(right));
    let mid = sorted.len() / 2;
    if sorted.len().is_multiple_of(2) {
        (sorted[mid - 1] + sorted[mid]) / 2.0
    } else {
        sorted[mid]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_mad_outliers() {
        let scores = vec![vec![0.1, 0.1, 0.9, 0.2], vec![0.2, 0.1, 0.8, 0.2]];
        let plan = plan_task_guided_compaction(&scores, None, 1.0).unwrap();
        assert_eq!(plan.retained_positions, vec![2]);
    }

    #[test]
    fn rejects_ragged_scores() {
        let scores = vec![vec![0.1], vec![0.2, 0.3]];
        assert!(matches!(
            plan_task_guided_compaction(&scores, None, 0.0),
            Err(BriefingError::RaggedScores)
        ));
    }
}
