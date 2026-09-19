"""Swappable reasoning backends. Codex reuses CLI login, never project API keys."""
import asyncio
import os
import shutil
import signal
import tempfile
from pathlib import Path

from .providers import OpenAIBrain, ProviderError
from .reasoning import ANSWER_INSTRUCTIONS, conversation_input


class CodexBrain:
    def __init__(self, executable="codex", model="gpt-5.6-terra", timeout=120, reasoning_effort="medium"):
        self.executable, self.model, self.timeout = executable, model, timeout
        if reasoning_effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Unsupported CODEX_REASONING_EFFORT")
        self.reasoning_effort = reasoning_effort

    @staticmethod
    def child_env():
        # Preserve the CLI's login location, but don't pass app secrets to the worker.
        allowed = {"PATH", "HOME", "CODEX_HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LANG", "LC_ALL"}
        return {key: value for key, value in os.environ.items() if key in allowed}

    async def answer(self, transcript: list[str]) -> str:
        executable = shutil.which(self.executable)
        if not executable:
            raise ProviderError("Codex CLI not found; install Codex and run codex login")
        prompt = ANSWER_INSTRUCTIONS + "\n\nConversation JSON:\n" + conversation_input(transcript)
        with tempfile.TemporaryDirectory(prefix="sparkie-codex-") as directory:
            output = Path(directory) / "answer.txt"
            command = [executable, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                       "--sandbox", "read-only", "--color", "never", "--cd", directory,
                       "-c", 'approval_policy="never"', "-c", 'web_search="disabled"',
                       "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
                       "-c", "features.shell_tool=false", "--output-last-message", str(output)]
            if self.model:
                command.extend(["--model", self.model])
            command.append("-")
            process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, env=self.child_env(), start_new_session=True,
            )
            try:
                await asyncio.wait_for(process.communicate(prompt.encode()), self.timeout)
            except (TimeoutError, asyncio.CancelledError) as exc:
                if process.returncode is None:
                    try:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise ProviderError("Codex backend timed out") from None
            if process.returncode:
                raise ProviderError(f"Codex exited with status {process.returncode}; check codex login status and model access")
            if not output.is_file() or output.stat().st_size > 65536:
                raise ProviderError("Codex returned no usable final message")
            answer = output.read_text().strip()
            if not answer:
                raise ProviderError("Codex returned an empty answer")
            return answer[:400]


def configured_brain(backend=None):
    backend = backend or os.getenv("SPARKIE_BACKEND") or "codex"
    if backend == "codex":
        timeout = float(os.getenv("CODEX_TIMEOUT_SECONDS") or "120")
        if not 0 < timeout <= 600:
            raise ValueError("CODEX_TIMEOUT_SECONDS must be between 0 and 600")
        return CodexBrain(model=os.getenv("CODEX_MODEL") or "gpt-5.6-terra", timeout=timeout,
                          reasoning_effort=os.getenv("CODEX_REASONING_EFFORT") or "medium")
    if backend == "openai":
        key, model = os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_MODEL")
        if not key or not model:
            raise ValueError("OpenAI backend requires OPENAI_API_KEY and OPENAI_MODEL in .env")
        return OpenAIBrain(key, model)
    raise ValueError("SPARKIE_BACKEND must be codex or openai")
