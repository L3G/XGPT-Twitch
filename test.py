import requests
import json

def update_player_data():
    """
    Update player data using the hardcoded UID and API key
    Prints full response details on error
    """
    # Hardcoded player UID
    player_uid = "403390083"
    
    # Hardcoded API key
    api_key = "107702406c06c403bec91048d3ea4a7923b68d627bb14ad538d955ab9f8fa3d3"
    
    # Define the API endpoint
    url = f"https://marvelrivalsapi.com/api/v1/player/{player_uid}/update"
    
    # Set up the headers with the API key
    headers = {
        "accept": "application/json",
        "X-API-Key": api_key
    }
    
    # Make the GET request
    try:
        response = requests.get(url, headers=headers)
        
        # Print response details regardless of status code
        print(f"Status Code: {response.status_code}")
        print("Headers:")
        for header, value in response.headers.items():
            print(f"  {header}: {value}")
        
        print("\nResponse Content:")
        try:
            # Try to parse and pretty-print JSON
            content = response.json()
            print(json.dumps(content, indent=2))
        except:
            # If not JSON, print raw content
            print(response.text)
        
        # Only continue if request was successful
        if response.status_code == 200:
            return response.json()
        else:
            print(f"\nError: Received status code {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"Exception occurred during request: {e}")
        return None

def main():
    print("Making API request to update player data...")
    result = update_player_data()
    
    if result:
        print("\nPlayer data update successful!")
    else:
        print("\nFailed to update player data. See details above.")

if __name__ == "__main__":
    main()