import os
import json
import re
import requests
import random
import time
import pytz
from datetime import datetime, timedelta
from flask import Flask, request, Response

# Configure OpenAI
import openai
openai.api_key = os.getenv("OPENAI_API_KEY", "REPLACE_ME_WITH_YOUR_OPENAI_KEY")

app = Flask(__name__)

##################################################
# Chatbot Configuration
##################################################
CONVERSATION_HISTORY = []

# Load banned words
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

# Search API configuration
GOOGLE_API_KEY = "AIzaSyDEpAVpDeJ4nHcEk8nkqN3MHpahM0VDcn4"
GOOGLE_SEARCH_CX = "3099754d9b7fb4d0f"

##################################################
# Marvel Rivals API Configuration
##################################################
MARVEL_RIVALS_API_KEY = "107702406c06c403bec91048d3ea4a7923b68d627bb14ad538d955ab9f8fa3d3"
MARVEL_RIVALS_BASE_URL = "https://marvelrivalsapi.com/api/v1"

# Cache for update calls to prevent rate limiting
UPDATE_CACHE = {}
UPDATE_CACHE_DURATION = 30 * 60  # 30 minutes in seconds
CACHE_FILE = "marvel_rivals_cache.json"

# Load cache from file if it exists
try:
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r") as f:
            UPDATE_CACHE = json.load(f)
except Exception as e:
    print(f"Error loading cache file: {e}")

# Rank mapping based on level
RANKS = {
    1: "Bronze 3",
    2: "Bronze 2",
    3: "Bronze 1",
    4: "Silver 3",
    5: "Silver 2",
    6: "Silver 1",
    7: "Gold 3",
    8: "Gold 2",
    9: "Gold 1",
    10: "Platinum 3",
    11: "Platinum 2",
    12: "Platinum 1",
    13: "Diamond 3",
    14: "Diamond 2",
    15: "Diamond 1",
    16: "Grandmaster 3",
    17: "Grandmaster 2",
    18: "Grandmaster 1",
    19: "Celestial 3",
    20: "Celestial 2",
    21: "Celestial 1",
    22: "Eternity",
    23: "One Above All",
}

##################################################
# Chatbot Helper Functions
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

def run_openai_chat(model: str, messages: list, params: dict = None) -> str:
    """
    Calls the OpenAI ChatCompletion API with the specified model and messages.
    `params` is optional and can include temperature, top_p, etc.
    Returns the assistant's message content as a string.
    """
    if params is None:
        params = {}

    # Ensure we remove anything not supported by OpenAI's parameters
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
# Marvel Rivals Helper Functions
##################################################
def convert_timestamp_to_date(timestamp):
    """Convert Unix timestamp to date in UTC"""
    try:
        dt = datetime.fromtimestamp(timestamp, pytz.UTC).date()
        return dt
    except Exception as e:
        # Return a far-future date to avoid matches
        return datetime(2099, 1, 1).date()

def save_update_cache():
    """Save the update cache to file"""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(UPDATE_CACHE, f)
    except Exception as e:
        print(f"Error saving cache file: {e}")

def should_update_player(player_id):
    """Check if we should update the player based on cache"""
    current_time = time.time()
    # Convert player_id to string for JSON compatibility
    player_id_str = str(player_id)
    last_update = float(UPDATE_CACHE.get(player_id_str, 0))
    
    time_since_last_update = current_time - last_update
    should_update = time_since_last_update >= UPDATE_CACHE_DURATION
    
    if should_update:
        # Update the cache timestamp
        UPDATE_CACHE[player_id_str] = current_time
        # Save cache to file
        save_update_cache()
        return True
    return False

def update_player_data(player_id):
    """Update player data via API"""
    update_headers = {
        "accept": "application/json",
        "X-API-Key": MARVEL_RIVALS_API_KEY
    }
    
    update_url = f"{MARVEL_RIVALS_BASE_URL}/player/{player_id}/update"
    
    try:
        update_response = requests.get(update_url, headers=update_headers)
        success = update_response.status_code == 200
        
        if success:
            # Record successful update in cache
            player_id_str = str(player_id)
            UPDATE_CACHE[player_id_str] = time.time()
            save_update_cache()
        
        return success, update_response.status_code, update_response.text
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)

def get_rank_from_level(level):
    """Get rank name from level"""
    return RANKS.get(level, "Unknown Rank")

##################################################
# Chatbot API Routes
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

    # Check if first word is "l8rbabe"
    if question.split()[0].lower() == "l8rbabe":
        # Remove the first word from the question
        parts = question.split(maxsplit=1)
        question = parts[1] if len(parts) > 1 else ""
        # New system prompt for l8rbabe mode
        dev_message = {
            "role": "system",
            "content": (
                "You are now in l8rbabe mode. You are a highly intellectual and witty chatbot. "
                "Provide responses that are insightful, humorous, and use modern slang. You can also use words like fuck, bitch, ass, shit, etc.. "
                "Keep your answers concise yet informative. Answers MUST be 400 characters or less."
            )
        }
        messages = [dev_message] + CONVERSATION_HISTORY + [
            {"role": "user", "content": question}
        ]
        cf_params = {}
    elif question.split()[0].lower() == "grumpyyrose":
        # Remove the first word from the question
        parts = question.split(maxsplit=1)
        question = parts[1] if len(parts) > 1 else ""
        question = question + " Keep your answer less than 400 characters long."
        # New system prompt for l8rbabe mode
        dev_message = {
            "role": "system",
            "content": (
                "You are now in grumpyyrose mode. You are a highly intellectual and witty chatbot. "
                "Provide responses that are insightful, humorous, and use modern slang. You can also use words like fuck, bitch, ass, shit, etc.. However, if the user wants to talk about movies or old shows, make fun of them and bully them."
                "Keep your answers concise yet informative. Answers MUST be 400 characters or less."
            )
        }
        messages = [dev_message] + CONVERSATION_HISTORY + [
            {"role": "user", "content": question}
        ]
        cf_params = {}
    elif question.startswith("pp"):
        # System prompt for "pp" mode
        dev_message = {
            "role": "system",
            "content": (
                "As a chatbot named Nightbot, my primary directive is to entertain and maintain decorum within the Twitch community. "
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
        # Default system prompt
        dev_message = {
            "role": "system",
            "content": (
                "You are a chatbot named Nightbot, that bullies the user and streamer with excessive and vulgar language "
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

    # Cut off the response if it exceeds 400 characters
    sanitized_answer = sanitized_answer.strip()[:400]

    # Remove certain chars for plain text
    for char in ['{', '}', '"']:
        sanitized_answer = sanitized_answer.replace(char, '')

    return Response(sanitized_answer, 200, mimetype="text/plain; charset=utf-8")

##################################################
# Marvel Rivals API Routes
##################################################
@app.route('/marvel-rivals/player/<player_id>/stats/today', methods=['GET'])
def get_player_stats_today(player_id):
    """
    Get overall win/loss stats for .Laina IGN using the new Tracker.gg API.
    Note: Since the new API doesn't separate matches by day, this returns overall stats.
    """
    new_api_url = "https://api.tracker.gg/api/v2/marvel-rivals/standard/profile/ign/.Laina"
    
    # Headers mimicking your browser request
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "max-age=0",
        "if-modified-since": "Sat, 01 Mar 2025 03:22:20 GMT",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0",
        "sec-ch-ua": "\"Not(A:Brand\";v=\"99\", \"Microsoft Edge\";v=\"133\", \"Chromium\";v=\"133\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\""
        # Optionally, you can include cookies if required by uncommenting the next line:
        # "cookie": "YOUR_COOKIE_STRING_HERE"
    }
    
    try:
        new_response = requests.get(new_api_url, headers=headers, timeout=10)
        if new_response.status_code != 200:
            return Response(
                f"Error fetching data: {new_response.status_code}",
                new_response.status_code,
                mimetype="text/plain; charset=utf-8"
            )
        
        # Check content type: if JSON, use it directly; else, try to extract JSON from a <pre> block.
        content_type = new_response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            api_data = new_response.json()
        else:
            match = re.search(r'<pre>(.*)</pre>', new_response.text, re.DOTALL)
            if not match:
                return Response("Error parsing API response", 500, mimetype="text/plain; charset=utf-8")
            json_str = match.group(1)
            api_data = json.loads(json_str)
    except Exception as e:
        return Response(f"Error fetching or parsing API data: {str(e)}",
                        500, mimetype="text/plain; charset=utf-8")
    
    try:
        # Get the level and compute the rank (using the existing mapping)
        level = api_data["data"]["metadata"]["level"]
        rank = get_rank_from_level(level)
        
        # Look for the segment with overall stats (metadata name "All")
        segments = api_data["data"].get("segments", [])
        segment = next((s for s in segments if s.get("metadata", {}).get("name") == "All"), None)
        if segment is None and segments:
            segment = segments[0]
        if segment is None:
            return Response("No stats segment found.", 404, mimetype="text/plain; charset=utf-8")
        
        stats = segment.get("stats", {})
        matches_played = stats.get("matchesPlayed", {}).get("value", 0)
        matches_won = stats.get("matchesWon", {}).get("value", 0)
        matches_lost = matches_played - matches_won
        
        if matches_played == 0:
            response_text = f"Rank {rank}. No competitive matches played."
        else:
            response_text = (f"Rank {rank}. They've won {matches_won}, lost {matches_lost} "
                             f"(out of {matches_played} matches).")
        
        return Response(response_text, 200, mimetype="text/plain; charset=utf-8")
    except Exception as e:
        return Response(f"Error processing player data: {str(e)}",
                        500, mimetype="text/plain; charset=utf-8")



@app.route('/marvel-rivals/debug/<player_id>', methods=['GET'])
def debug_player_data(player_id):
    """Debug endpoint to see raw API data for a player"""
    debug_info = {
        "player_id": player_id,
        "timestamp": datetime.now().isoformat(),
        "competitive_history": None,
        "all_modes_history": None
    }
    
    # Headers for API requests
    headers = {
        "accept": "application/json",
        "x-api-key": MARVEL_RIVALS_API_KEY
    }
    
    # Check competitive mode (game_mode=2)
    try:
        comp_url = f"{MARVEL_RIVALS_BASE_URL}/player/{player_id}/match-history?season=1.5&skip=0&game_mode=2"
        comp_response = requests.get(comp_url, headers=headers)
        if comp_response.status_code == 200:
            debug_info["competitive_history"] = comp_response.json()
    except Exception as e:
        debug_info["competitive_error"] = str(e)
    
    # Check all modes (game_mode=0)
    try:
        all_url = f"{MARVEL_RIVALS_BASE_URL}/player/{player_id}/match-history?season=1.5&skip=0&game_mode=0"
        all_response = requests.get(all_url, headers=headers)
        if all_response.status_code == 200:
            debug_info["all_modes_history"] = all_response.json()
    except Exception as e:
        debug_info["all_modes_error"] = str(e)
    
    return Response(json.dumps(debug_info, indent=2), 200, mimetype="application/json")

@app.route('/marvel-rivals/player/<player_id>/clear-cache', methods=['GET'])
def clear_player_cache(player_id):
    """Clear the update cache for a player"""
    player_id_str = str(player_id)
    if player_id_str in UPDATE_CACHE:
        del UPDATE_CACHE[player_id_str]
        save_update_cache()
        return Response(f"Cache cleared for player {player_id}", 200, mimetype="text/plain; charset=utf-8")
    else:
        return Response(f"No cache entry found for player {player_id}", 200, mimetype="text/plain; charset=utf-8")

@app.route('/marvel-rivals/status', methods=['GET'])
def marvel_rivals_status():
    """Show status of the Marvel Rivals cache"""
    cache_info = {}
    current_time = time.time()
    
    for player_id, last_update in UPDATE_CACHE.items():
        time_since = current_time - float(last_update)
        minutes_ago = round(time_since / 60, 1)
        next_update = round((UPDATE_CACHE_DURATION - time_since) / 60, 1)
        
        cache_info[player_id] = {
            "last_update_minutes_ago": minutes_ago,
            "next_update_in_minutes": max(0, next_update)
        }
    
    return Response(json.dumps(cache_info, indent=2), 200, mimetype="application/json")

##################################################
# Main Entry Point
##################################################
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)