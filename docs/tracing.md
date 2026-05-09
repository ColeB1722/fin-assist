# Tracing & Observability

fin-assist emits OpenTelemetry spans across two processes — the CLI and the hub — and joins them so one `fin` invocation reads as one browsable flow in Phoenix (or any OTLP-compatible backend).

## Trace topology

```text
CLI process                                Hub process
━━━━━━━━━━━                                ━━━━━━━━━━━
cli.do  (root, one per invocation)
│   fin_assist.cli.invocation_id = <uuid>  (also in Baggage)
│   fin_assist.cli.command = "do"
│
├── HTTP GET  /health                 ────► (hub: FastAPIInstrumentor span)
├── HTTP GET  /agents                 ────► (hub: FastAPIInstrumentor span)
├── HTTP GET  /agents/<name>          ────► (hub: FastAPIInstrumentor span)
└── HTTP POST /agents/<name>/         ────► HTTP POST /agents/<name>/
       (a2a-sdk Client.send_message)         (a2a-sdk DefaultRequestHandler)
                                              │
                                              └── fin_assist.task
                                                  fin_assist.cli.invocation_id = <uuid>  ← join key
                                                  fin_assist.task.state = running | paused_for_approval
                                                                          | resumed_from_approval (transient)
                                                                          | completed | failed
                                                  ├── fin_assist.step
                                                  │   └── fin_assist.tool_execution
                                                  └── (upstream LLM/tool spans from
                                                       pydantic-ai → OpenInference bridge:
                                                       gen_ai.*, llm.*)
```

**Why one CLI trace + one hub trace, not one shared `trace_id`:** HTTP boundaries already open fresh traces hub-side; making them share a `trace_id` would require suppressing the hub's natural request tracing, which would also suppress useful per-request timing data. Instead we join via `fin_assist.cli.invocation_id` (Baggage-propagated) — a single attribute lookup in Phoenix shows all spans across both processes for one invocation.

## Instrumented request flow

Full sequence diagram of a `SendStreamingMessage` call, with span emissions and state transitions called out. The structural overview without spans lives in [`docs/architecture.md`](architecture.md#request-flow-overview).

```mermaid
sequenceDiagram
    participant C as CLI Client
    participant H as Hub<br/>(sub-app + DefaultRequestHandler)
    participant E as Executor
    participant B as AgentBackend<br/>(PydanticAIBackend)
    participant SH as StreamHandle
    participant CS as ContextStore
    participant LLM as LLM Provider

    C->>C: cli_root_span (invocation_id in Baggage)
    C->>H: SendStreamingMessage (JSON-RPC + SSE)
    Note over C,H: invocation_id propagated via Baggage header

    H->>E: execute(context, event_queue)
    E->>E: start fin_assist.task span<br/>state=running
    E->>E: updater.start_work() → WORKING

    E->>B: check_credentials()
    B-->>E: [] or [missing providers]

    alt Credentials missing
        Note over E,B: raises MissingCredentialsError
        E->>E: task.state=failed
        E->>E: updater.requires_auth() → AUTH_REQUIRED
        H-->>C: SSE: TaskStatusUpdateEvent (auth_required)
    else Credentials present
        E->>CS: load(context_id)
        CS-->>E: bytes or None
        E->>B: deserialize_history(bytes)
        B-->>E: message_history (prior turns)

        E->>B: convert_history([current_message])
        B-->>E: framework messages (this turn)

        E->>B: run_stream(messages=history)
        B-->>E: StreamHandle
        Note over B,LLM: backend holds LLM connection<br/>emits gen_ai.* / llm.* spans

        loop Token-by-token
            SH-->>E: text delta (async iter)
            E->>H: updater.add_artifact(append=true, last_chunk=false)
            H-->>C: SSE: TaskArtifactUpdateEvent
        end

        E->>H: updater.add_artifact("", last_chunk=true)
        H-->>C: SSE: TaskArtifactUpdateEvent (last_chunk=true)

        alt Tool call needs approval
            E->>E: emit fin_assist.approval_request span
            E->>CS: save_pause_state(SpanContext, user_input)
            E->>E: task.state=paused_for_approval
            E->>E: updater.requires_input() → AUTH_REQUIRED
            H-->>C: SSE: TaskStatusUpdateEvent (paused)
            Note over C: cli.approval_wait child span<br/>(human think-time, subtractable)
            C->>H: resume (new HTTP request → new hub trace)
            H->>E: new fin_assist.task span<br/>Link(resume_from_approval)
            E->>E: emit fin_assist.approval_decided span<br/>Link(approval_for)
        end

        alt Exception during stream
            E->>E: task.state=failed
            E->>E: updater.failed() → FAILED
            H-->>C: SSE: TaskStatusUpdateEvent (failed)
        end

        E->>SH: await result()
        SH-->>E: RunResult (output, serialized_history, new_message_parts)

        E->>CS: save(context_id, serialized_history)

        loop new_message_parts (thinking blocks, etc.)
            E->>H: updater.update_status(WORKING, message=part)
            H-->>C: SSE: TaskStatusUpdateEvent (WORKING + message)
        end

        alt Structured output (non-str)
            E->>B: convert_result_to_part(output)
            B-->>E: Part (data + json_schema metadata)
            E->>H: updater.add_artifact(structured, new artifact_id)
            H-->>C: SSE: TaskArtifactUpdateEvent (structured)
        end

        E->>E: task.state=completed
        E->>E: updater.complete() → COMPLETED
        H-->>C: SSE: TaskStatusUpdateEvent (completed)
    end
```

## HITL pause/resume

Tool calls requiring human approval pause the hub task (`requires_input`) and the CLI waits for the user's y/N. The resume opens a **new** HTTP request → new hub trace → new `fin_assist.task` span. Continuity across the pause:

1. At pause, the hub executor emits `fin_assist.approval_request` (a zero-duration span — OTel spans cannot be reopened across processes, so the "wait" is represented implicitly by the time-gap between this span's end and the resumed trace's start).
2. The executor persists the paused span's `SpanContext` + original `user_input` via `ContextStore.save_pause_state`.
3. At resume, the new task span carries a `Link(resume_from_approval)` back to the paused `approval_request` span, and emits `fin_assist.approval_decided` as its first child with a second `Link(approval_for)` to the same target.
4. The CLI root span stays open across the approval wait (no 30-min timeout today — tracked as follow-up), and wraps the y/N prompt in a `cli.approval_wait` child so dashboards can subtract human think-time.

In Phoenix the two hub traces appear as siblings, joined by the Link (rendered as "jump to related trace") and by the shared `fin_assist.cli.invocation_id` attribute. The CLI trace is a third sibling that contains both hub traces as link targets via its child HTTP spans.

## Task state attribute

`fin_assist.task.state` is the canonical Phoenix filter for task-level queries. Values come from `TaskStateValues` in `hub/tracing_attrs.py`:

- `running` — initial state when the task span starts
- `paused_for_approval` — set when an approval-gated tool call pauses execution
- `resumed_from_approval` — set transiently when a paused task is resumed; overwritten by `completed`/`failed` before the span ends, so it's only observable on in-flight spans
- `completed` — terminal success
- `failed` — terminal failure

One attribute with a small enum keeps queries simple — one equality check per state instead of a compound predicate across several booleans.

## Skill spans

Today, only the CLI-side stamp is wired:

- **CLI-side**: `cli_root_span(skill="commit")` stamps `fin_assist.cli.skill` on the CLI root span when a skill is pre-loaded via `--skill` flag or the prompt-as-skill shortcut.

Two further hooks exist as scaffolding but are **not yet invoked** — tracked as [#123](https://github.com/ColeB1722/fin-assist/issues/123):

- `_TaskTracer.emit_skill_load_span()` (defined; would emit `fin_assist.skill_load` carrying `fin_assist.skill.id`, `fin_assist.skill.entry_point`, `fin_assist.skill.tools_unlocked`) — would fire when a skill loads during a task.
- `start_task_span(skill_id=...)` (parameter accepted; would stamp `fin_assist.skill.id` on the `fin_assist.task` span) — would fire when a skill was pre-loaded before the task started.

## Noise suppression

Two upstream instrumentors were disabled because they produce high-volume, low-value spans:

- **a2a-sdk**'s `@trace_class` decorator wraps every internal queue / task-store method with a `SpanKind.SERVER` span. Disabled via `OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false` (vendor-supported env off-switch). The `os.environ.setdefault(...)` call lives in `src/fin_assist/__init__.py`, not in `setup_tracing` — it must run *before* `a2a` is imported, since a2a-sdk reads the env var at module top level. Operators can override by exporting the var explicitly before launching.
- **FastAPIInstrumentor**'s per-SSE-chunk `http.response.body` span. Dropped in the export pipeline by `DropSpansProcessor` (in `tracing_shared.py`), which keys on `asgi.event.type = "http.response.body"` (not span name, so instrumentor-version renames don't break us).

## Attribute hygiene

Three classes of leaked/duplicate attributes are scrubbed at `on_end` before export:

- `logfire.*` — pydantic-ai uses logfire as its internal tracing front-end; the `logfire.msg` / `logfire.json_schema` attrs ride along with no value for downstream consumers.
- `final_result` on `agent run` spans — already duplicated as `output.value` (OpenInference) and `pydantic_ai.all_messages`. Dropping saves ~5–30KB per trace.
- Duplicate `session.id` when identical to `fin_assist.context.id`.

## Files

- `src/fin_assist/tracing_shared.py` — process-agnostic processors and helpers shared by the CLI and hub: `DropSpansProcessor`, `TruncatingSpanProcessor`, attribute scrubbing, and `_GracefulOTLPExporter` (the OTLP exporter that degrades cleanly when Phoenix isn't running)
- `src/fin_assist/hub/tracing.py` — hub-side TracerProvider builder (composes the shared processors with OTLP + JSONL file sinks)
- `src/fin_assist/hub/tracing_attrs.py` — centralized attribute names and enum values (`FinAssistAttributes`, `TaskStateValues`, `SpanNames`)
- `src/fin_assist/cli/tracing.py` — CLI-side tracer; `cli_root_span` / `approval_wait_span` context managers + `HTTPXClientInstrumentor` integration
- `src/fin_assist/__init__.py` — sets `OTEL_INSTRUMENTATION_A2A_SDK_ENABLED=false` at import time (must precede a2a-sdk import)
- `src/fin_assist/agents/pydantic_ai_tracing.py` — pydantic-ai → OpenInference bridge (the one place that imports `openinference.instrumentation.pydantic_ai`; kept isolated so the hub stays framework-neutral)

## Local trace inspection

Tracing is enabled by default in dev (`FIN_TRACING__ENABLED=true` in `devenv.nix`). Spans are written to:

- **Phoenix** if running at `localhost:6006` (rich UI for trace exploration)
- **`./.fin/traces.jsonl`** always — line-delimited JSON for grep/jq inspection without a UI
