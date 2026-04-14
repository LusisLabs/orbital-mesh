use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AgentRole {
    Planner,
    Critic,
    Refiner,
    Judger,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Agent {
    pub name: &'static str,
    pub role: AgentRole,
}

pub fn default_agents() -> [Agent; 4] {
    [
        Agent {
            name: "Planner",
            role: AgentRole::Planner,
        },
        Agent {
            name: "Critic",
            role: AgentRole::Critic,
        },
        Agent {
            name: "Refiner",
            role: AgentRole::Refiner,
        },
        Agent {
            name: "Judger",
            role: AgentRole::Judger,
        },
    ]
}
