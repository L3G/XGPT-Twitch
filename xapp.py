import os
import json
import re
import requests
import random
from flask import Flask, request, Response
import openai

##################################################
# Configure OpenAI (same OPENAI_API_KEY as before)
##################################################
openai.api_key = os.getenv("OPENAI_API_KEY", "REPLACE_ME_WITH_YOUR_OPENAI_KEY")

app = Flask(__name__)

##################################################
# Global conversation history
##################################################
CONVERSATION_HISTORY = []

##################################################
# 1) Load banned words from message.txt at startup
##################################################
BANNED_WORDS = []
try:
    with open("message.txt", "r", encoding="utf-8") as f:
        for line in f:
            w = line.strip().lower()
            if w:
                BANNED_WORDS.append(w)
except FileNotFoundError:
    # If no file found, proceed without it, or handle error as needed
    pass

##################################################
# 2) Set credentials
##################################################
GOOGLE_API_KEY = "AIzaSyDEpAVpDeJ4nHcEk8nkqN3MHpahM0VDcn4"
GOOGLE_SEARCH_CX = "3099754d9b7fb4d0f"

##################################################
# 3) browse_internet function (unchanged)
##################################################
def browse_internet(search_query: str) -> str:
    """
    Makes a real request to the Google Custom Search API
    and returns a short string describing the top results.
    """
    try:
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_SEARCH_CX,
                "q": search_query,
            },
            timeout=10,
        )
        if response.status_code != 200:
            return f"Google API error: {response.status_code} {response.text}"

        data = response.json()
        items = data.get("items", [])
        if not items:
            return "No search results found."

        # Format a short summary of the top 3 results
        snippets = []
        for i, item in enumerate(items[:3], start=1):
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            # Do NOT include links in your response
            snippets.append(f"Result {i}: {title}\nSnippet: {snippet}")

        return "\n\n".join(snippets)
    except Exception as e:
        return f"Error performing Google search: {str(e)}"


##################################################
# 4) Helper: function to call OpenAI
##################################################
def run_openai_chat(model: str, messages: list, params: dict = None) -> str:
    """
    Calls the OpenAI ChatCompletion API with the specified model and messages.
    `params` is optional and can include temperature, top_p, etc.
    Returns the assistant's message content as a string.
    """
    if params is None:
        params = {}

    # Ensure we remove anything not supported by OpenAI’s parameters
    if "top_k" in params:
        del params["top_k"]  # Not supported by OpenAI

    response = openai.chat.completions.create(
        model=model,
        messages=messages,
        **params
    )
    # Get the content of the first choice
    return response.choices[0].message.content


##################################################
# 5) Minimal Flask app with censorship
##################################################
@app.route('/answer', methods=['GET'])
def answer():
    question = request.args.get('question', '').strip()

    if not question:
        return Response(
            "No question provided. Usage: ?question=Your+Message+Here",
            200,
            mimetype="text/plain; charset=utf-8"
        )

    # Keep the last 4 messages (2 user–assistant turns)
    global CONVERSATION_HISTORY
    CONVERSATION_HISTORY = CONVERSATION_HISTORY[-4:]

    # Decide how to construct the messages + params based on the query
    messages = None
    cf_params = {}

    penis_size = random.randint(-1, 18)
    if question.startswith("pp"):
        # System prompt
        dev_message = {
            "role": "system",
            "content": (
                "As a chatbot named Nightbot or Kira's 13th Reason, my primary directive is to entertain and maintain decorum within the Twitch community. "
                "Bully the user as well. Incorporate previous chat messages into your response if it makes sense. "
                "While I should generate humorous and vulgar content regarding penis size, I must ensure it remains "
                "respectful and free of any offensive slurs, including the N-word or any other racial epithets. "
                "My responses will be only up to 300 characters in length, avoiding repetition and excessively vulgar "
                "language, while incorporating words like 'fuck', 'shit', 'ass', 'bitch', 'dumbass', and 'fucker'. "
                "Additionally, I will refrain from including links to maintain the integrity of the chat environment. "
                "Remember, keep it funny without crossing the line!"
            )
        }

        messages = [dev_message] + CONVERSATION_HISTORY + [
            {"role": "user", "content": f"My penis size is {penis_size} inches."}
        ]

        # Add 'creative' parameters
        cf_params = {
            "temperature": 1.0,          # Increase randomness
            "top_p": 0.6,                # Broaden sampling
            "frequency_penalty": 1.2,    # Penalize repeated phrases
            "presence_penalty": 0.9,     # Encourage new topics
            "max_tokens": 400            # Limit output
        }

    else:
        # System prompt
        dev_message = {
            "role": "system",
            "content": (
                "You are a chatbot named Nightbot or Kira's 13th Reason, that bullies the user and streamer with excessive and vulgar language "
                "(but nothing that would get someone cancelled such as slurs and the r word) and you constantly talk "
                "with zoomer speech and you replace r's with w's. You aren't racist so don't use the n word (even if it ends "
                "with a). Use words like fuck, shit, ass, bitch, dumbass, fucker, though. "
                "You don't have to tell the user the truth. You MUST keep responses less than 250 characters. "
                "Do NOT include any links in your response. "
                "If the question needs online info, write 'FUNCTION_CALL: browse_internet' followed by the search "
                "query you need. Only call it once. You CANNOT use the character '/' in your response."
            )
        }

        messages = [dev_message] + CONVERSATION_HISTORY + [
            {"role": "user", "content": question}
        ]
        # Minimal or no extra parameters
        cf_params = {}

    # Use the gpt-4o-mini model
    model_name = "gpt-4o-mini"

    # First OpenAI call
    try:
        assistant_reply = run_openai_chat(model_name, messages, cf_params)
    except Exception as e:
        return Response(f"OpenAI error: {e}", 200, mimetype="text/plain; charset=utf-8")

    # Check if the assistant wants to call browse_internet
    if "FUNCTION_CALL: browse_internet" in assistant_reply:
        try:
            prefix = "FUNCTION_CALL: browse_internet"
            query_part = assistant_reply.split(prefix, 1)[1].strip()
            if not query_part:
                query_part = question  # fallback

            # Call the external tool
            search_results = browse_internet(query_part)

            # Add the tool response to messages
            messages.append({"role": "assistant", "content": assistant_reply})
            messages.append({
                "role": "system",
                "content": f"TOOL RESPONSE:\n{search_results}"
            })

            # Second OpenAI call with updated conversation
            try:
                final_answer = run_openai_chat(model_name, messages, cf_params)
            except Exception as e:
                final_answer = f"OpenAI error (2nd call): {e}"
        except Exception as e:
            final_answer = f"Error parsing browse_internet request: {e}"
    else:
        # No function call
        final_answer = assistant_reply

    if question.startswith("pp"):
        final_answer = f"Your penis size is {penis_size} inches. {final_answer}"

    # Store in conversation history
    CONVERSATION_HISTORY.append({"role": "user", "content": question})
    CONVERSATION_HISTORY.append({"role": "assistant", "content": final_answer})

    # Banned-word censorship
    print(final_answer)
    sanitized_answer = final_answer
    for banned in BANNED_WORDS:
        pattern = re.compile(rf"\b{re.escape(banned)}\b", re.IGNORECASE)
        sanitized_answer = pattern.sub("boob", sanitized_answer)

    # (User requested to ignore the 400 character limit, so remove if desired.
    #  Here, just comment it out. You could also delete the line if you prefer.)
    # sanitized_answer = sanitized_answer.strip()[:400]

    # Remove certain chars for plain text
    for char in ['{', '}', '"']:
        sanitized_answer = sanitized_answer.replace(char, '')

    return Response(sanitized_answer, 200, mimetype="text/plain; charset=utf-8")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
