# app/core/worker.py — оба worker'а для единого приложения.
from core.llama_worker import LlamaWorker
from core.ollama_worker import Worker as OllamaWorker

__all__ = ["LlamaWorker", "OllamaWorker", "Worker"]
Worker = OllamaWorker  # для совместимости с импортами из старого кода
