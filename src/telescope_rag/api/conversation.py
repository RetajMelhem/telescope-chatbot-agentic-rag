"""Publish generated prose with application-owned citations and unchanged source records."""

from telescope_rag.api.hours_responses import HoursChatResponse
from telescope_rag.graph.contracts import WorkflowRun

_TEXT = {
    "en": {
        "unknown": "I couldn't find that information in the website material available to me.",
        "excluded": (
            "I can explain the public website information, but I can't carry out private "
            "actions or provide personalized medical advice."
        ),
    },
    "ar": {
        "unknown": "لم أجد هذه المعلومة ضمن معلومات الموقع المتاحة لي.",
        "excluded": (
            "أستطيع شرح معلومات الموقع العامة، لكن لا يمكنني تنفيذ إجراءات خاصة "
            "أو تقديم نصائح طبية شخصية."
        ),
    },
    "ar-JO": {
        "unknown": "ما لقيت هالمعلومة ضمن معلومات الموقع المتوفرة عندي.",
        "excluded": (
            "بقدر أشرحلك معلومات الموقع العامة، بس ما بقدر أنفّذ طلبات خاصة "
            "أو أعطيك نصيحة طبية شخصية."
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
        if (
            question.hours is None
            and entry is not None
            and (entry.status != question.status or entry.reason_code != question.reason_code)
        ):
            raise ValueError("conversation_outcome_mismatch")
        if (
            question.hours is None
            and question.status == "candidate"
            and (entry is None or not entry.sentences)
        ):
            raise ValueError("conversation_answer_missing")
        if entry and entry.sentences:
            if question.hours is not None or question.status != "candidate":
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
                refs = " ".join(f"[{citations[i]}]" for i in sentence.chunk_ids)
                sentences.append(f"{sentence.text.strip()} {refs}")
            answer = " ".join(sentences)
        elif question.hours is None and (
            question.status == "excluded"
            or (question.status == "unknown" and question.reason_code == "not_found")
        ):
            answer = _TEXT[response.language][question.status]
        else:
            # Existing computed hours and explicit URL choices keep their trusted
            # application presentation. The model never recomputes a time result.
            answer = question.answer
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
