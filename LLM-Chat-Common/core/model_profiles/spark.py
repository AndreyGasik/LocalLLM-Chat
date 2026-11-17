# core/model_profiles/spark.py
#
# Профиль Spark-X2.x (SparkLLM / iFlytek) — перенос из LLM-Chat (Ollama),
# где он живёт в core/tool_parsing.py (_is_spark_model,
# _build_spark_tools_instruction) и core/worker.py (tool_mode == "spark").
#
# Spark обучена вызывать инструменты в формате
#   <tool_call>имя<arg_key>..</arg_key><arg_value>..</arg_value></tool_call>
# (см. карточку модели и vLLM-парсер spark25). Разбор такого вызова делает
# core/tool_parsing.py::_parse_argkv_tool_calls; здесь — только то, что
# касается самой модели: распознавание по имени, параметры сэмплинга и
# компактная инструкция в её родном формате (без JSON-схем).

from core.tool_parsing import _is_spark_model, _build_spark_tools_instruction

# Имена без подчёркивания — как у остальных профилей (nanbeige.py). Реализация
# лежит в общем модуле LLM-Chat-Common/tool_parsing.py и одинакова для обоих
# проектов (Ollama-версия импортирует те же функции напрямую).
is_spark_model = _is_spark_model
build_spark_tools_instruction = _build_spark_tools_instruction


def spark_payload_overrides() -> dict:
    """Карточка Spark-X2.6 рекомендует repetition_penalty = 1. Штраф за
    повторы > 1 портит закрывающие теги вызова (</arg_value>) и русские
    окончания. llama-server принимает repeat_penalty прямо в теле
    /v1/chat/completions."""
    return {"repeat_penalty": 1.0}
