"use client";

import {
  CheckCircle2,
  Circle,
  CircleAlert,
  CircleDotDashed,
  CircleX,
} from "lucide-react";
import { AnimatePresence, LayoutGroup, motion, useReducedMotion, type Variants } from "framer-motion";
import React from "react";

import { cn } from "../../lib/utils";

type TaskStatus = "completed" | "in-progress" | "pending" | "need-help" | "failed";
type TaskPriority = "high" | "medium" | "low";

export interface AgentLifecycleSubtask {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  tools?: string[];
}

export interface AgentLifecycleTask {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  level: number;
  dependencies: string[];
  subtasks: AgentLifecycleSubtask[];
}

const initialTasks: AgentLifecycleTask[] = [
  {
    id: "1",
    title: "Harper-696 voice session boundary",
    description: "Load the operator-safe voice agent posture before touching Mesh state.",
    status: "in-progress",
    priority: "high",
    level: 0,
    dependencies: [],
    subtasks: [
      {
        id: "1.1",
        title: "Bind assistant identity",
        description: "Agent name is Harper-696. Its role is operator assistance, not Mesh authority.",
        status: "completed",
        priority: "high",
        tools: ["LiveKit agent", "Harper-696/src/agent.py"],
      },
      {
        id: "1.2",
        title: "Apply authority boundary",
        description: "Every mutation must name a state slice and wait for operator confirmation.",
        status: "in-progress",
        priority: "high",
        tools: ["Mesh policy", "operator identity"],
      },
      {
        id: "1.3",
        title: "Detect unavailable live voice backend",
        description: "If LiveKit credentials or room token endpoints are absent, keep this UI in read-only composer mode.",
        status: "need-help",
        priority: "medium",
        tools: ["LIVEKIT_URL", "token endpoint"],
      },
    ],
  },
  {
    id: "2",
    title: "Intent to Mesh read model",
    description: "Convert the operator prompt into read-only Mesh inspection before any action.",
    status: "in-progress",
    priority: "high",
    level: 0,
    dependencies: ["1"],
    subtasks: [
      {
        id: "2.1",
        title: "Load dashboard context",
        description: "Use /api/operator/dashboard as the product read model for readiness, approvals, and proof gaps.",
        status: "completed",
        priority: "high",
        tools: ["/api/operator/dashboard", "DashboardPayload"],
      },
      {
        id: "2.2",
        title: "Inspect active run",
        description: "Read run timeline, evidence graph, delivery context, agent attempts, and audit proof.",
        status: "in-progress",
        priority: "high",
        tools: ["/api/runs/{id}", "/api/runs/{id}/evidence-graph"],
      },
      {
        id: "2.3",
        title: "Name uncertainty",
        description: "If a live endpoint is missing, report unavailable state instead of inventing status.",
        status: "pending",
        priority: "medium",
        tools: ["connection state", "load state"],
      },
    ],
  },
  {
    id: "3",
    title: "Agent and proposal lane drilldown",
    description: "Expose Hermes, Goose, Codex, and other proposal lanes as evidence providers only.",
    status: "pending",
    priority: "medium",
    level: 1,
    dependencies: ["1", "2"],
    subtasks: [
      {
        id: "3.1",
        title: "Map agent task attempts",
        description: "Show selected attempts, risk flags, allowed paths, test commands, and reconciliation posture.",
        status: "pending",
        priority: "high",
        tools: ["AgentTask", "AgentAttempt"],
      },
      {
        id: "3.2",
        title: "Route Hermes explanation",
        description: "Use Hermes for blocker explanation and proposed actions while Mesh owns steering.",
        status: "pending",
        priority: "medium",
        tools: ["chat_with_hermes", "explain_blockers"],
      },
      {
        id: "3.3",
        title: "Keep lanes advisory",
        description: "Connector certification and policy gates decide whether any lane can do more than propose.",
        status: "pending",
        priority: "high",
        tools: ["connector certification", "orchestration topology"],
      },
    ],
  },
  {
    id: "4",
    title: "Mutation preview and confirmation",
    description: "Generate a structured preview before approve, resume, override, launch, or cancel.",
    status: "pending",
    priority: "high",
    level: 0,
    dependencies: ["2"],
    subtasks: [
      {
        id: "4.1",
        title: "Build state-slice declaration",
        description: "State slice, action, target, and policy posture must be visible before a mutating call.",
        status: "pending",
        priority: "high",
        tools: ["SteeringCommand", "RunSession"],
      },
      {
        id: "4.2",
        title: "Resolve approval posture",
        description: "Block, approval-required, and allowed states come from Mesh policy and admission data.",
        status: "pending",
        priority: "high",
        tools: ["mesh.run_admission.v1", "ApprovalQueuePacket"],
      },
      {
        id: "4.3",
        title: "Write audit path",
        description: "Successful steering must be reflected as run events, approval records, Merkle proof, and exportable audit.",
        status: "pending",
        priority: "medium",
        tools: ["RunEvent", "MerkleSnapshot", "RunExportPackage"],
      },
    ],
  },
  {
    id: "5",
    title: "Evidence and lifecycle canvas",
    description: "Push the operator from chat into a deeper lifecycle view across Mesh state.",
    status: "pending",
    priority: "medium",
    level: 1,
    dependencies: ["2", "4"],
    subtasks: [
      {
        id: "5.1",
        title: "Show proof gaps",
        description: "Surface missing pilot packet and Darkharness evidence before production claims.",
        status: "pending",
        priority: "high",
        tools: ["PilotGoNoGoPacket", "DarkharnessPilotPacket"],
      },
      {
        id: "5.2",
        title: "Open topology context",
        description: "Let operators drill into active run topology, signal, evidence, artifacts, and Merkle continuity.",
        status: "pending",
        priority: "medium",
        tools: ["React Flow", "InfraGraph", "EvidenceGraph"],
      },
      {
        id: "5.3",
        title: "Preserve read-only fallback",
        description: "When Harper or Mesh live state is unavailable, the workflow remains inspectable and non-mutating.",
        status: "pending",
        priority: "medium",
        tools: ["LoadState", "backend availability"],
      },
    ],
  },
];

const smoothEase = [0.2, 0.65, 0.3, 0.9] as const;
const badgeEase = [0.34, 1.56, 0.64, 1] as const;

function statusIcon(status: TaskStatus, sizeClass: string) {
  if (status === "completed") return <CheckCircle2 className={cn(sizeClass, "text-green-500")} />;
  if (status === "in-progress") return <CircleDotDashed className={cn(sizeClass, "text-blue-500")} />;
  if (status === "need-help") return <CircleAlert className={cn(sizeClass, "text-yellow-500")} />;
  if (status === "failed") return <CircleX className={cn(sizeClass, "text-red-500")} />;
  return <Circle className={cn(sizeClass, "text-muted-foreground")} />;
}

function statusClass(status: TaskStatus) {
  if (status === "completed") return "bg-green-100 text-green-700";
  if (status === "in-progress") return "bg-blue-100 text-blue-700";
  if (status === "need-help") return "bg-yellow-100 text-yellow-700";
  if (status === "failed") return "bg-red-100 text-red-700";
  return "bg-muted text-muted-foreground";
}

function nextStatus(status: TaskStatus): TaskStatus {
  const statuses: TaskStatus[] = ["pending", "in-progress", "need-help", "failed", "completed"];
  const index = statuses.indexOf(status);
  return statuses[(index + 1) % statuses.length] ?? "pending";
}

export interface AgentLifecyclePlanProps {
  activePrompt?: string;
  className?: string;
  lifecycleTasks?: AgentLifecycleTask[];
}

export default function AgentLifecyclePlan({ activePrompt, className, lifecycleTasks }: AgentLifecyclePlanProps) {
  const [tasks, setTasks] = React.useState<AgentLifecycleTask[]>(lifecycleTasks ?? initialTasks);
  const [expandedTasks, setExpandedTasks] = React.useState<string[]>(["1", "2"]);
  const [expandedSubtasks, setExpandedSubtasks] = React.useState<Record<string, boolean>>({});
  const prefersReducedMotion = useReducedMotion();

  React.useEffect(() => {
    if (lifecycleTasks) setTasks(lifecycleTasks);
  }, [lifecycleTasks]);

  const toggleTaskExpansion = (taskId: string) => {
    setExpandedTasks((previous) =>
      previous.includes(taskId) ? previous.filter((id) => id !== taskId) : [...previous, taskId],
    );
  };

  const toggleSubtaskExpansion = (taskId: string, subtaskId: string) => {
    const key = `${taskId}-${subtaskId}`;
    setExpandedSubtasks((previous) => ({ ...previous, [key]: !previous[key] }));
  };

  const toggleTaskStatus = (taskId: string) => {
    setTasks((previous) =>
      previous.map((task) => {
        if (task.id !== taskId) return task;
        const status = nextStatus(task.status);
        return {
          ...task,
          status,
          subtasks: task.subtasks.map((subtask) => ({
            ...subtask,
            status: status === "completed" ? "completed" : subtask.status,
          })),
        };
      }),
    );
  };

  const toggleSubtaskStatus = (taskId: string, subtaskId: string) => {
    setTasks((previous) =>
      previous.map((task) => {
        if (task.id !== taskId) return task;
        const subtasks = task.subtasks.map((subtask) =>
          subtask.id === subtaskId
            ? { ...subtask, status: (subtask.status === "completed" ? "pending" : "completed") as TaskStatus }
            : subtask,
        );
        return {
          ...task,
          subtasks,
          status: subtasks.every((subtask) => subtask.status === "completed") ? "completed" : task.status,
        };
      }),
    );
  };

  const taskVariants: Variants = {
    hidden: { opacity: 0, y: prefersReducedMotion ? 0 : -5 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        type: prefersReducedMotion ? "tween" : "spring",
        stiffness: 500,
        damping: 30,
        duration: prefersReducedMotion ? 0.2 : undefined,
      },
    },
  };

  const subtaskListVariants: Variants = {
    hidden: { opacity: 0, height: 0, overflow: "hidden" },
    visible: {
      height: "auto",
      opacity: 1,
      overflow: "visible",
      transition: {
        duration: 0.25,
        staggerChildren: prefersReducedMotion ? 0 : 0.05,
        when: "beforeChildren",
        ease: smoothEase,
      },
    },
  };

  const subtaskVariants: Variants = {
    hidden: { opacity: 0, x: prefersReducedMotion ? 0 : -10 },
    visible: {
      opacity: 1,
      x: 0,
      transition: {
        type: prefersReducedMotion ? "tween" : "spring",
        stiffness: 500,
        damping: 25,
        duration: prefersReducedMotion ? 0.2 : undefined,
      },
    },
    exit: {
      opacity: 0,
      x: prefersReducedMotion ? 0 : -10,
      transition: { duration: 0.15 },
    },
  };

  const subtaskDetailsVariants: Variants = {
    hidden: { opacity: 0, height: 0, overflow: "hidden" },
    visible: {
      opacity: 1,
      height: "auto",
      overflow: "visible",
      transition: { duration: 0.25, ease: smoothEase },
    },
  };

  const statusBadgeVariants: Variants = {
    initial: { scale: 1 },
    animate: {
      scale: prefersReducedMotion ? 1 : [1, 1.08, 1],
      transition: { duration: 0.35, ease: badgeEase },
    },
  };

  return (
    <div className={cn("h-full overflow-auto bg-background p-2 text-foreground", className)}>
      <motion.div
        className="overflow-hidden rounded-lg border border-border bg-card shadow"
        initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 10 }}
        animate={{ opacity: 1, y: 0, transition: { duration: 0.3, ease: smoothEase } }}
      >
        <div className="border-b border-border px-4 py-3">
          <span className="text-[11px] font-bold uppercase text-[#89cdbb]">Agent lifecycle</span>
          <h3 className="m-0 mt-1 text-base font-semibold text-foreground">Harper-696 to Mesh state flow</h3>
          <p className="m-0 mt-1 text-sm text-muted-foreground">
            {activePrompt
              ? `Current prompt: ${activePrompt}`
              : "Send a prompt to push into the lifecycle and inspect which Mesh state slices are involved."}
          </p>
        </div>
        <LayoutGroup>
          <div className="overflow-hidden p-4">
            <ul className="space-y-1 overflow-hidden">
              {tasks.map((task, index) => {
                const isExpanded = expandedTasks.includes(task.id);
                const isCompleted = task.status === "completed";

                return (
                  <motion.li
                    key={task.id}
                    className={cn(index !== 0 && "mt-1 pt-2")}
                    initial="hidden"
                    animate="visible"
                    variants={taskVariants}
                  >
                    <motion.div
                      className="group flex items-center rounded-md px-3 py-1.5"
                      whileHover={{ backgroundColor: "rgba(255,255,255,0.04)", transition: { duration: 0.2 } }}
                    >
                      <motion.button
                        type="button"
                        className="mr-2 flex-shrink-0 cursor-pointer border-0 bg-transparent p-0"
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleTaskStatus(task.id);
                        }}
                        whileTap={{ scale: 0.9 }}
                        whileHover={{ scale: 1.1 }}
                        title={`Set ${task.title} status`}
                      >
                        <AnimatePresence mode="wait">
                          <motion.span
                            key={task.status}
                            initial={{ opacity: 0, scale: 0.8, rotate: -10 }}
                            animate={{ opacity: 1, scale: 1, rotate: 0 }}
                            exit={{ opacity: 0, scale: 0.8, rotate: 10 }}
                            transition={{ duration: 0.2, ease: smoothEase }}
                          >
                            {statusIcon(task.status, "h-[18px] w-[18px]")}
                          </motion.span>
                        </AnimatePresence>
                      </motion.button>

                      <button
                        type="button"
                        className="flex min-w-0 flex-grow cursor-pointer items-center justify-between border-0 bg-transparent p-0 text-left text-foreground"
                        onClick={() => toggleTaskExpansion(task.id)}
                      >
                        <span className="mr-2 flex-1 truncate">
                          <span className={cn(isCompleted && "text-muted-foreground line-through")}>{task.title}</span>
                        </span>

                        <span className="flex flex-shrink-0 items-center space-x-2 text-xs">
                          {task.dependencies.length > 0 ? (
                            <span className="mr-2 flex items-center">
                              <span className="flex flex-wrap gap-1">
                                {task.dependencies.map((dependency, dependencyIndex) => (
                                  <motion.span
                                    key={dependency}
                                    className="rounded bg-secondary/40 px-1.5 py-0.5 text-[10px] font-medium text-secondary-foreground shadow-sm"
                                    initial={{ opacity: 0, scale: 0.9 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    transition={{ duration: 0.2, delay: dependencyIndex * 0.05 }}
                                    whileHover={{ y: -1, backgroundColor: "rgba(255,255,255,0.1)", transition: { duration: 0.2 } }}
                                  >
                                    {dependency}
                                  </motion.span>
                                ))}
                              </span>
                            </span>
                          ) : null}

                          <motion.span
                            className={cn("rounded px-1.5 py-0.5", statusClass(task.status))}
                            variants={statusBadgeVariants}
                            initial="initial"
                            animate="animate"
                            key={task.status}
                          >
                            {task.status}
                          </motion.span>
                        </span>
                      </button>
                    </motion.div>

                    <AnimatePresence mode="wait">
                      {isExpanded && task.subtasks.length > 0 ? (
                        <motion.div
                          className="relative overflow-hidden"
                          variants={subtaskListVariants}
                          initial="hidden"
                          animate="visible"
                          exit="hidden"
                          layout
                        >
                          <div className="absolute bottom-0 left-[20px] top-0 border-l-2 border-dashed border-muted-foreground/30" />
                          <ul className="mb-1.5 ml-3 mr-2 mt-1 space-y-0.5 border-muted">
                            {task.subtasks.map((subtask) => {
                              const subtaskKey = `${task.id}-${subtask.id}`;
                              const isSubtaskExpanded = expandedSubtasks[subtaskKey];

                              return (
                                <motion.li
                                  key={subtask.id}
                                  className="group flex flex-col py-0.5 pl-6"
                                  onClick={() => toggleSubtaskExpansion(task.id, subtask.id)}
                                  variants={subtaskVariants}
                                  initial="hidden"
                                  animate="visible"
                                  exit="exit"
                                  layout
                                >
                                  <motion.div
                                    className="flex flex-1 items-center rounded-md p-1"
                                    whileHover={{ backgroundColor: "rgba(255,255,255,0.04)", transition: { duration: 0.2 } }}
                                    layout
                                  >
                                    <motion.button
                                      type="button"
                                      className="mr-2 flex-shrink-0 cursor-pointer border-0 bg-transparent p-0"
                                      onClick={(event) => {
                                        event.stopPropagation();
                                        toggleSubtaskStatus(task.id, subtask.id);
                                      }}
                                      whileTap={{ scale: 0.9 }}
                                      whileHover={{ scale: 1.1 }}
                                      layout
                                      title={`Toggle ${subtask.title}`}
                                    >
                                      <AnimatePresence mode="wait">
                                        <motion.span
                                          key={subtask.status}
                                          initial={{ opacity: 0, scale: 0.8, rotate: -10 }}
                                          animate={{ opacity: 1, scale: 1, rotate: 0 }}
                                          exit={{ opacity: 0, scale: 0.8, rotate: 10 }}
                                          transition={{ duration: 0.2, ease: smoothEase }}
                                        >
                                          {statusIcon(subtask.status, "h-3.5 w-3.5")}
                                        </motion.span>
                                      </AnimatePresence>
                                    </motion.button>

                                    <span className={cn("cursor-pointer text-sm", subtask.status === "completed" && "text-muted-foreground line-through")}>
                                      {subtask.title}
                                    </span>
                                  </motion.div>

                                  <AnimatePresence mode="wait">
                                    {isSubtaskExpanded ? (
                                      <motion.div
                                        className="mt-1 overflow-hidden border-l border-dashed border-foreground/20 pl-5 text-xs text-muted-foreground"
                                        variants={subtaskDetailsVariants}
                                        initial="hidden"
                                        animate="visible"
                                        exit="hidden"
                                        layout
                                      >
                                        <p className="py-1">{subtask.description}</p>
                                        {subtask.tools && subtask.tools.length > 0 ? (
                                          <div className="mb-1 mt-0.5 flex flex-wrap items-center gap-1.5">
                                            <span className="font-medium text-muted-foreground">State and tools:</span>
                                            <div className="flex flex-wrap gap-1">
                                              {subtask.tools.map((tool, toolIndex) => (
                                                <motion.span
                                                  key={tool}
                                                  className="rounded bg-secondary/40 px-1.5 py-0.5 text-[10px] font-medium text-secondary-foreground shadow-sm"
                                                  initial={{ opacity: 0, y: prefersReducedMotion ? 0 : -5 }}
                                                  animate={{
                                                    opacity: 1,
                                                    y: 0,
                                                    transition: { duration: 0.2, delay: toolIndex * 0.05 },
                                                  }}
                                                  whileHover={{ y: -1, backgroundColor: "rgba(255,255,255,0.1)", transition: { duration: 0.2 } }}
                                                >
                                                  {tool}
                                                </motion.span>
                                              ))}
                                            </div>
                                          </div>
                                        ) : null}
                                      </motion.div>
                                    ) : null}
                                  </AnimatePresence>
                                </motion.li>
                              );
                            })}
                          </ul>
                        </motion.div>
                      ) : null}
                    </AnimatePresence>
                  </motion.li>
                );
              })}
            </ul>
          </div>
        </LayoutGroup>
      </motion.div>
    </div>
  );
}
