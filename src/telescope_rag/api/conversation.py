"""Publish generated prose with application-owned citations and unchanged source records."""

from telescope_rag.api.hours_presentation import _answer as hours_answer
from telescope_rag.api.hours_responses import HoursChatResponse
from telescope_rag.graph.contracts import WorkflowRun

_TEXT = {
    "en": {
        "unknown": "I don't have enough information to confirm that.",
        "excluded": (
            "I can help with information about our services, but I can't carry out private "
            "actions or provide personal medical advice in this chat."
        ),
    },
    "ar": {
        "unknown": "لا تتوفر لدي معلومات كافية لتأكيد ذلك.",
        "excluded": (
            "يمكنني مساعدتك بمعلومات عن خدمات مركزنا، لكن لا يمكنني تنفيذ طلبات خاصة "
            "أو تقديم نصائح طبية شخصية في هذه المحادثة."
        ),
    },
    "ar-JO": {
        "unknown": "ما عندي معلومات كافية أأكدلك هالشي.",
        "excluded": (
            "بقدر أساعدك بمعلومات عن خدمات مركزنا، بس ما بقدر أنفّذ طلبات خاصة "
            "أو أعطيك نصيحة طبية شخصية بهالمحادثة."
        ),
    },
}


def project_conversation(response: HoursChatResponse, run: WorkflowRun) -> HoursChatResponse:
    parts = {p.part_id: p for p in run.conversation.parts} if run.conversation else {}
    if parts and set(parts) != {q.id for q in response.questions}:
        raise ValueError("conversation_coverage_mismatch")
    questions = []
    for question in response.questions:
        entry = parts.get(question.id)
        if entry is not None and (
            entry.status != question.status or entry.reason_code != question.reason_code
        ):
            raise ValueError("conversation_outcome_mismatch")
        if question.status == "candidate" and (entry is None or not entry.sentences):
            raise ValueError("conversation_answer_missing")
        if entry and entry.sentences:
            if question.status != "candidate":
                raise ValueError("conversation_outcome_mismatch")
            citations = {
                c.chunk_id: c.id for c in response.citations if c.question_id == question.id
            }
            sentences = []
            for sentence in entry.sentences:
                if (
                    any(i not in citations for i in sentence.chunk_ids)
                    or not sentence.text.strip()
                    or "[" in sentence.text
                    or "]" in sentence.text
                ):
                    raise ValueError("conversation_citation_mismatch")
                # Validate support IDs above, but keep technical references in
                # the structured sources panel rather than the chat prose.
                sentences.append(sentence.text.strip())
            answer = " ".join(sentences)
        elif question.hours is None and (
            question.status == "excluded"
            or (question.status == "unknown" and question.reason_code == "not_found")
        ):
            answer = _TEXT[response.language][question.status]
        else:
            # Unknown/ambiguous hours and explicit URL choices keep application
            # presentation. The model cannot change their computed outcomes.
            answer = (
                hours_answer(question.hours, response.language)
                if question.hours is not None
                else question.answer
            )
        questions.append(question.model_copy(update={"answer": answer}))
    paragraphs = []
    for question in questions:
        if question.status == "excluded" and question.answer in paragraphs:
            # One shared boundary explanation can cover several excluded actions;
            # the API still retains every original part and its separate outcome.
            continue
        paragraphs.append(question.answer)
    return response.model_copy(
        update={
            "questions": tuple(questions),
            "answer": "\n\n".join(paragraphs),
        }
    )
