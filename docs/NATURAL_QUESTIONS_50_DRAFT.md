# Approved everyday user questions: 50 requests

Prepared and approved by the user on 2026-10-18, including both price questions.
**Question approval is complete. Paid evaluation has not run.** The original
filename is retained so existing links continue to work.

There are 25 everyday intents, each written as one independent Jordanian Arabic
question and one natural English question: **25 Arabic + 25 English = 50 requests**.
The pairs ask for equivalent information. These are authored examples of plausible
user questions, not collected user traffic, adversarial challenges or a statistical
sample of production demand. All requests have empty conversation history.

The first six intents preserve the user's examples. Source inspection used the
public v0.1.0 release knowledge ZIP: 107 saved documents / 955 chunks. Both the ZIP
hash and all 116 runtime file hashes/sizes matched the release manifest. No website
refresh, bot request, query embedding, model call or database operation ran.

The source review identifies 24 supported intents (48 questions) and one intent
without a documented exact amount (two questions). This describes evidence in the
saved knowledge, not whether the chatbot can retrieve it or answer correctly.

| Intent | Jordanian Arabic (`ar-JO`) | English (`en`) | Expected source coverage |
| --- | --- | --- | --- |
| U01 | اعطيني رقمكم | What's your phone number? | Supported |
| U02 | وين موقع المركز؟ | Where's the center located? | Supported |
| U03 | ايش الفرق بين الـ PRK والـ LASIK؟ | What's the difference between PRK and LASIK? | Supported |
| U04 | هل عندكم عملية تصحيح نظر؟ | Do you offer vision correction surgery? | Supported |
| U05 | هل بتعملوا إبراز شفايف؟ | Do you offer lip enhancement? | Supported |
| U06 | مين الطاقم الطبي عندكم؟ | Who's on your medical team? | Supported; directory coverage matters |
| U07 | عندكم رقم واتساب؟ | Do you have a WhatsApp number? | Supported |
| U08 | من أي ساعة لأي ساعة بتداوموا؟ | What are your opening hours? | Supported |
| U09 | بتفتحوا يوم الجمعة؟ | Are you open on Fridays? | Supported |
| U10 | في مواقف سيارات عند المركز؟ | Is there parking at the center? | Supported |
| U11 | بتتعاملوا مع شركات التأمين؟ | Do you accept insurance? | Supported at a general level |
| U12 | بقدر أدفع بالبطاقة أو كليك؟ | Can I pay by card or CliQ? | Supported |
| U13 | شو لازم أجيب معي عالزيارة؟ | What should I bring to my appointment? | Supported |
| U14 | عادةً قديش بتاخد الزيارة؟ | How long does an appointment usually take? | Supported; duration varies |
| U15 | مين دكاترة العيون عندكم؟ | Which eye doctors work at the center? | Supported; explicit specialties matter |
| U16 | مين دكاترة الجلدية عندكم؟ | Which dermatologists work at the center? | Supported; explicit specialties matter |
| U17 | شو هي عملية الـ PRK؟ | What is PRK surgery? | Supported |
| U18 | شو هي عملية الليزك؟ | What is LASIK surgery? | Supported |
| U19 | بتعملوا عمليات مي بيضا؟ | Do you perform cataract surgery? | Supported |
| U20 | في عندكم بوتوكس؟ | Do you offer Botox? | Supported |
| U21 | بتعملوا فيلر للخدود؟ | Do you offer cheek fillers? | Supported |
| U22 | في عندكم علاج لحب الشباب؟ | Do you treat acne? | Supported |
| U23 | بتعالجوا آثار حب الشباب؟ | Do you treat acne scars? | Supported |
| U24 | شو العيادات الموجودة عندكم؟ | What clinics do you have at the center? | Supported at the published specialty level |
| U25 | قديش سعر عملية تصحيح النظر؟ | How much does vision correction surgery cost? | Exact amount not found in the reviewed knowledge |

## Review and scoring boundaries

- U25 is a normal price inquiry. Its intended response acknowledges that an exact
  price is not documented in the available knowledge, without inventing an amount.
  Published general information about obtaining an estimate after consultation
  may be included with its own source. Those passages are context, not proof of
  an exact surgery price. Score missing-information handling separately; supporting
  evidence recall for the exact amount is null, not zero or one.
- U11 supports general insurance acceptance; it does not establish acceptance of
  any named insurer or coverage of a particular procedure.
- U06 needs review against the complete primary medical directory. U15 and U16
  use explicit specialties. Department placement alone does not establish a
  doctor's specialty. Directory completeness must not be inferred from a few
  top-k hits or treated as a simple single-passage hit.
- U03, U17 and U18 permit source-based explanations. They do not request personal
  suitability, a prescription or a guaranteed result or recovery date.
- U22 and U23 remain separate: active acne and acne scars are different claims.
  Non-equivalent English/Arabic source passages must not be silently substituted.
- U24 asks about published clinics/specialties, not a real-time staff or private
  appointment inventory.
- Keep each language pair together in any later development/evaluation split.
  Fifty requests represent 25 paired intents, not 50 independent observations.
  This visible draft is not an unseen holdout or a frozen, fully scored benchmark.
- Source witnesses are selected known positives. The source-backed answer key and
  scoring rules are now prepared; see the [evaluation runbook](NATURAL_EVALUATION_50.md).

## Files and next step

The [request-only JSONL](../tests/fixtures/evaluation/natural_questions_50_v1/requests.jsonl)
contains exactly `case_id`, `language`, `query` and empty `history`. IDs are
`U01-ar-JO`, `U01-en` through `U25-ar-JO`, `U25-en`. It has no gold answers, evidence
IDs, outcomes or reviewer notes. Do not embed the question set into clinic knowledge
or add runtime rules for its wording.

The downloaded knowledge and local source-review receipts remain under ignored
`artifacts/natural-questions-50-source-v1/`; they are not Git content or serving data.
The receipt records source bindings and selected passages separately from requests.

The user selected `install-mvp.ps1 -Version v0.1.0` and confirmed installation
and key setup on 2026-10-19. The evaluator uses that installed Docker API over
HTTP; credentials stay with the installer. The approved question bytes remain
unchanged. See [current status](../PROJECT_STATUS.md) for the execution result
and [the runbook](NATURAL_EVALUATION_50.md) for measurement limits.
