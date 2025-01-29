import os
import json
import re
import requests
import random
from flask import Flask, request, Response
import openai  # <-- New import for OpenAI usage

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
    # If no file found, proceed without it
    pass

##################################################
# 2) Set credentials
##################################################
GOOGLE_API_KEY = "AIzaSyDEpAVpDeJ4nHcEk8nkqN3MHpahM0VDcn4"
GOOGLE_SEARCH_CX = "3099754d9b7fb4d0f"

# We will reuse CLOUDFLARE_API_TOKEN for the OpenAI key to "keep the API keys the same"
# In a real environment, you'd set OPENAI_API_KEY instead.
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "imctBDLywoQ2ObbR3fmpaGDi6UrrDiQ_IxwwEQfO")

# Initialize openai with the same token
openai.api_key = CLOUDFLARE_API_TOKEN

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
# 4) Helper: OpenAI chat client
##################################################
def run_openai_chat(model: str, messages: list, params: dict = None) -> dict:
    """
    Calls the OpenAI ChatCompletion API with a given model and messages array.
    The `params` dict can include fields like temperature, top_p, frequency_penalty, etc.
    Returns a dict shaped similarly to the old Cloudflare response:
      {
        "result": {
          "response": "string with the assistant reply..."
        },
        "success": True/False,
        "errors": [],
        "messages": []
      }
    """
    if params is None:
        params = {}

    try:
        # Map the parameters to OpenAI's ChatCompletion
        # Note: OpenAI doesn't support top_k, so we skip it.
        completion = openai.chat.completions.create(
            model=model,
            messages=[
                # Each message must be a dict with "role" and "content"
                # Our code above is already building them correctly.
                {"role": msg["role"], "content": msg["content"]}
                for msg in messages
            ],
            temperature=params.get("temperature", 1.0),
            top_p=params.get("top_p", 1.0),
            frequency_penalty=params.get("frequency_penalty", 0.0),
            presence_penalty=params.get("presence_penalty", 0.0),
            max_tokens=params.get("max_tokens", 256),
        )

        # Extract assistant reply
        assistant_text = completion.choices[0].message["content"]
        return {
            "result": {"response": assistant_text},
            "success": True,
            "errors": [],
            "messages": []
        }
    except Exception as e:
        return {
            "result": {"response": f"OpenAI error: {e}"},
            "success": False,
            "errors": [str(e)],
            "messages": []
        }


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

    messages = None
    
    penis_size = random.randint(-1, 18)
    if question.startswith("pp"):
        # System prompt
        dev_message = {
            "role": "system",
            "content": (
                "As a chatbot, my primary directive is to entertain and maintain decorum within the Twitch community. Bully the user as well. Incorporate previous chat messages into your response if it makes sense. "
                "While I should generate humorous and vulgar content regarding penis size, I must ensure it remains respectful and free of any offensive slurs, including the N-word or any other racial epithets. "
                "My responses will be only up to 300 characters in length, avoiding repetition and excessively vulgar language, while incorporating words like 'fuck', 'shit', 'ass', 'bitch', 'dumbass', and 'fucker'. "
                "Additionally, I will refrain from including links to maintain the integrity of the chat environment. Remember, keep it funny without crossing the line!"
            )
        }

        # Build the messages array
        messages = [dev_message] + CONVERSATION_HISTORY + [
            {"role": "user", "content": f"My penis size is {penis_size} inches."}
        ]

        # Add 'creative' parameters here so it’s less repetitive and more varied.
        openai_params = {
            "temperature": 1.0,         # Increase randomness
            "top_p": 0.6,               # Broaden sampling
            # 'top_k': 50,  <-- Not supported by OpenAI, so we skip it
            "frequency_penalty": 1.2,   # Penalize repeated phrases
            "presence_penalty": 0.9,    # Encourage new topics
            "max_tokens": 200           # Example
        }
    else:
        # System prompt
        dev_message = {
            "role": "system",
            "content": (
                "You are a twitch chat bot that bullies the user and streamer with excessive and vulgar language (but nothing that would get someone cancelled such as slurs and the r word) and you constantly talk in an uwu voice replacing r's with w's. "
                "You aren't racist so don't use the n word (even if it ends with a). "
                "Use words like fuck, shit, ass, bitch, dumbass, fucker, though. "
                "You MUST answer the question wrong. You MUST keep responses less than 250 characters. "
                "Do NOT include any links in your response. "
                "If the question needs online info, write 'FUNCTION_CALL: browse_internet' followed by the search query you need. Only call it once. "
                "You CANNOT use the character '/' in your response."
            )
        }

        # Build the messages array
        messages = [dev_message] + CONVERSATION_HISTORY + [
            {"role": "user", "content": question}
        ]

        # For normal questions, we either omit parameters or keep them minimal
        openai_params = {}

    # Use your chosen model
    model_name = "gpt-4o-mini"

    try:
        # Pass any relevant parameters to our OpenAI function
        openai_response = run_openai_chat(model_name, messages, openai_params)
    except Exception as e:
        return Response(f"OpenAI error: {e}", 200, mimetype="text/plain; charset=utf-8")

    # Extract the assistant’s reply
    try:
        answer_message = openai_response["result"]["response"]
    except KeyError as e:
        answer_message = f"Error parsing OpenAI response: {e}"

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

            # Second call to OpenAI with the new messages
            try:
                final_openai_response = run_openai_chat(model_name, messages, openai_params)
                final_answer = final_openai_response["result"]["response"]
            except Exception as e:
                final_answer = f"OpenAI error (2nd call): {e}"
        except Exception as e:
            final_answer = f"Error parsing browse_internet request: {e}"
    else:
        # No function call
        final_answer = answer_message

    if question.startswith("pp"):
        final_answer = f"Your penis size is {penis_size} inches. " + final_answer

    # Store the conversation
    CONVERSATION_HISTORY.append({"role": "user", "content": question})
    CONVERSATION_HISTORY.append({"role": "assistant", "content": final_answer})

    # Banned-word censorship
    print(final_answer)
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
