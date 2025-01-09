import os
import openai
from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv()

app = Flask(__name__)

# Use an environment variable for your API key (recommended for security)
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.route('/answer', methods=['GET'])
def answer():
    question = request.args.get('question', '').strip()
    if not question:
        return jsonify({"error": "No question provided"}), 400

    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini-2024-07-18",  # GPT-4o-mini model name
            messages=[
                {"role": "developer", "content": "You are a sassy assistant in a twitch chat."},
                {"role": "user", "content": question}
            ],
            max_tokens=60,
            temperature=0.7
        )
        # Extract response text and truncate to 400 characters
        answer_text = response.choices[0].message.content.strip()[:400]
        return jsonify({"answer": answer_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # By default, Flask listens on port 5000
    app.run(host='0.0.0.0', port=5000)