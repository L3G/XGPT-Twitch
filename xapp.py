import os
import json
import re
import requests
from flask import Flask, request, Response

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
# Cloudflare AI constants
CLOUDFLARE_API_BASE_URL = "https://api.cloudflare.com/client/v4/accounts/7ffbbc9f21ae89f4ee0191308466a12f/ai/run"
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "imctBDLywoQ2ObbR3fmpaGDi6UrrDiQ_IxwwEQfO")

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
# 4) Helper: Cloudflare AI client
##################################################
def run_cloudflare_ai(model: str, messages: list) -> dict:
    """
    Calls the Cloudflare AI REST API with a given model and messages array.
    Returns the parsed JSON response as a dict.
    """
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"
    }
    # Workers AI supports passing chat messages as JSON:
    payload = {
        "messages": messages
    }

    url = f"{CLOUDFLARE_API_BASE_URL}/{model}"
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()  # Raises on 4xx/5xx errors

    return resp.json()  # Should have keys: result, success, errors, messages


##################################################
# 5) Minimal Flask app with censorship
##################################################
@app.route('/answer', methods=['GET'])
def answer():
    question = request.args.get('question', '').strip()

    # Because StreamElements only shows output if the status is 200,
    # we'll ALWAYS return 200, even if the user didn't provide a question.
    if not question:
        return Response(
            "No question provided. Usage: ?question=Your+Message+Here",
            200,
            mimetype="text/plain; charset=utf-8"
        )

    # Keep the last 4 messages (2 user–assistant turns)
    global CONVERSATION_HISTORY
    CONVERSATION_HISTORY = CONVERSATION_HISTORY[-4:]

    # System prompt
    dev_message = {
        "role": "system",
        "content": (
            "You are a twitch chat bot that bullies the user and streamer with excessive and vulgar language (but nothing that would get someone cancelled such as slurs and the r word)."
            "You aren't racist so don't use the n word (even if it ends with a)."
            "Use words like fuck, shit, ass, bitch, dumbass, fucker, though. "
            "You will answer the question even if it's wrong. Keep responses less than 400 characters. "
            "Do NOT include any links in your response. "
            "If the question needs online info, write 'FUNCTION_CALL: browse_internet' followed by "
            "the search query you need. Only call it once."
            "You CANNOT use the character '/' in your response."
        )
    }

    # Build the messages array
    messages = [dev_message] + CONVERSATION_HISTORY + [
        {"role": "user", "content": question}
    ]

    # Use your chosen model
    model_name = "@hf/thebloke/openhermes-2.5-mistral-7b-awq"

    try:
        # First call to Cloudflare AI
        cf_response = run_cloudflare_ai(model_name, messages)
    except Exception as e:
        return Response(f"Cloudflare AI error: {e}", 200, mimetype="text/plain; charset=utf-8")

    # Extract the assistant’s reply from cf_response["result"]["response"]
    try:
        answer_message = cf_response["result"]["response"]
    except KeyError as e:
        answer_message = f"Error parsing Cloudflare AI response: {e}"

    # Check if the assistant wants to call browse_internet
    if "FUNCTION_CALL: browse_internet" in answer_message:
        # Extract the query after "FUNCTION_CALL: browse_internet"
        try:
            prefix = "FUNCTION_CALL: browse_internet"
            query_part = answer_message.split(prefix, 1)[1].strip()
            if not query_part:
                query_part = question  # fallback

            # Call the tool
            search_results = browse_internet(query_part)

            # Add the tool response to our conversation
            messages.append({"role": "assistant", "content": answer_message})
            messages.append({
                "role": "system",
                "content": f"TOOL RESPONSE:\n{search_results}"
            })

            # Second call to Cloudflare AI with the new messages
            try:
                final_cf_response = run_cloudflare_ai(model_name, messages)
                final_answer = final_cf_response["result"]["response"]
            except Exception as e:
                final_answer = f"Cloudflare AI error (2nd call): {e}"
        except Exception as e:
            final_answer = f"Error parsing browse_internet request: {e}"
    else:
        # No function call
        final_answer = answer_message

    # Store the conversation
    CONVERSATION_HISTORY.append({"role": "user", "content": question})
    CONVERSATION_HISTORY.append({"role": "assistant", "content": final_answer})

    # 6) Replace banned words with <CENSORED>
    #    For each banned word, we do a whole-word regex replace
    sanitized_answer = final_answer
    for banned in BANNED_WORDS:
        # \b matches word boundaries, ignoring case
        pattern = re.compile(rf"\b{re.escape(banned)}\b", re.IGNORECASE)
        sanitized_answer = pattern.sub("boob", sanitized_answer)

    # Truncate to 400 chars & remove certain chars for plain text
    sanitized_answer = sanitized_answer.strip()[:400]
    for char in ['{', '}', '"']:
        sanitized_answer = sanitized_answer.replace(char, '')

    # Return 200 OK so StreamElements can parse it
    return Response(sanitized_answer, 200, mimetype="text/plain; charset=utf-8")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
