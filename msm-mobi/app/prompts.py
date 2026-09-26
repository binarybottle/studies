"""Participant-facing copy inside the task, in one place so the research team
can revise wording without touching flow logic. The consent and finish pages
are in main.py, since they are whole pages rather than chat messages.

Braced fields are interpolated at runtime.
"""

ANSWER_1 = "Using the scale above, what is your answer? Enter a whole number from 0 to 100."

CONFIDENCE_1 = (
    "How confident are you in that answer? Enter a whole number from 0 to 100, "
    "where 0 is not at all confident and 100 is completely confident."
)

# Reads back the participant's own Answer Score 1.
TEXT_1 = "You rated that {answer_score_1} out of 100. What made you give that score?"

# User Text Response 2 and 3 have no prompt message of their own: the LLM
# reply that precedes them asks for the response itself. These are the input
# placeholders, and they are the fallback affordance if a reply ever fails to
# close on a question.
TEXT_PLACEHOLDER = {
    "text_1": "Type your response...",
    "text_2": "Type your reply...",
    "text_3": "Type your reply...",
}

# Answer Score 2 restates the Question as a new message.
ANSWER_2 = "Thinking about it again:\n\n{question_text}\n\nEnter a whole number from 0 to 100."

CONFIDENCE_2 = (
    "How confident are you in that answer now? Enter a whole number from 0 to 100, "
    "where 0 is not at all confident and 100 is completely confident."
)

ACTIVATION = (
    "Right now, how activated do you feel, physically and emotionally? Enter a whole "
    "number from 0 to 100, where 0 is completely calm and 100 is extremely activated."
)

GATE = "That's the end of this part. Take a moment if you need one, then continue when you're ready."

PRACTICE_INTRO = (
    "We'll start with a practice round so you can get used to how this works. "
    "It works exactly like the rest of the session, and your answers here are not part of the main results."
)

FIRST_REAL_BLOCK_INTRO = "That's the end of the practice round. The session starts now."

CONFIDENCE_SCALE_LOW = "Not at all confident"
CONFIDENCE_SCALE_HIGH = "Completely confident"

ACTIVATION_SCALE_LOW = "Completely calm"
ACTIVATION_SCALE_HIGH = "Extremely activated"

START_SCREEN_BODY = (
    "You'll read a series of short, imagined scenarios: a practice round, then twelve more. "
    "For each one you'll give a numeric answer to a question, briefly explain your thinking, "
    "exchange a few messages with an AI assistant about your view, and then answer the "
    "question again.\n\n"
    "There are no right or wrong answers, and nothing here is a test of knowledge. Answer "
    "based on the scenario as described; you don't need to share anything personal. Please "
    "type your responses in your own words rather than pasting them.\n\n"
    "Treat each scenario on its own. They're independent, so there's no need to stay "
    "consistent from one to the next. You can't go back to a previous answer once you've "
    "submitted it.\n\n"
    "If you close this page by accident, open the study link from Prolific again and you "
    "will pick up where you left off."
)

END_SCREEN_TITLE = "All done"
END_SCREEN_BODY = (
    "That's the end of the session. Thank you for taking part.\n\n"
    "Use the button below to register your completion on Prolific."
)
