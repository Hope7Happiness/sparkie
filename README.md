# Sparkie

以独立参与者身份加入线上会议的实时 AI agent：安静监听，被唤醒后参与讨论、执行后台任务，并在会后整理纪要。

技术栈：**Deepgram = ears + mouth · Codex CLI / OpenAI API = brain · Zoom = body**。

提供无 key 模拟 primitive；Deepgram 真实语音合成→流式转录检查已通过，本机 Codex CLI 的上下文回答也已通过实测。**Zoom 原生 adapter 待实现，尚未完成真实入会。**

```bash
uv sync --frozen
bash scripts/primitive.sh
uv run --frozen python -m unittest discover -s tests -v
```

需要 Python 3.11+ 和 uv。首次安装依赖后，模拟模式不需要网络、SDK、Docker 或账号。生成的 `output/primitive/run.json` 与静音 WAV 均明确标为模拟产物。

- [三人第一步分工](docs/team-first-steps.md)
- [人工配置清单：A / B / C 并行准备](docs/manual-setup.md)
- [primitive 运行方式、接口和限制](docs/primitive.md)
- [技术验证记录](docs/platform-validation.md)
- [完整产品计划](prompt)

最高优先级：先证明 Sparkie 可以加入真实会议，在被叫到时迅速播放“我在”。
