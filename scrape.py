import sys
import time
import requests
from requests.exceptions import HTTPError
from http import HTTPStatus
from bs4 import BeautifulSoup, Tag
import os
import json
import google.generativeai as genai

# Replace with your actual Google Cloud API Key
API_KEY = os.environ.get("API_KEY")
MIN_STARS = 20

EXCLUDED_USERS = ["nesttyy"]  # Add more users to this list if needed

def scrape_github_page(query, page):
    """Scrapes a single page of GitHub search results.

    Args:
        query (str): The search query.
        page (int): The page number to scrape.

    Returns:
        list: A list of dictionaries containing link, description, and stars for repositories on the page.
    """

    retries = 3
    retry_codes = [
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    ]

    url = f"https://github.com/search?q={query}&type=repositories&s=stars&o=desc&p={page}"
    repositories = []

    for n in range(retries):
        try:
            response = requests.get(url)
            response.raise_for_status()  # Raise for any HTTP errors
            soup = BeautifulSoup(response.content, "html.parser")
            results_list = soup.find("div", {"data-testid": "results-list"})

            if results_list is None:
                sys.exit("Seems the html structure has changed since last time, time to code")

            if type(results_list) is Tag:
                results = results_list.find_all("div", recursive=False)
            else:
                results = []

            for result in results:
                link_element = result.find("a", href=True)
                if link_element:
                    link = link_element['href']
                    # Extract the username from the link
                    username = link.split("/")[1].lower()

                    if username in [user.lower() for user in EXCLUDED_USERS]:  # Check if user is excluded (case-insensitive)
                        print(f"Skipping result: {link} (user: {username})")
                        continue

                    description_element = link_element.parent.parent.parent.find_next_sibling("div")
                    description = description_element.children.__next__().text.strip() if description_element and description_element.children else link  # Use link if description is missing
                    stars_element = link_element.parent.parent.parent.find_next_sibling("ul").find("a")
                    stars = int(stars_element.text.strip().replace(',', '')) if stars_element else None

                    repositories.append({"link": link, "description": description, "stars": stars})

            return repositories

        except HTTPError as exc:
            code = exc.response.status_code
            print(exc.response.headers)
            if code in retry_codes:
                # retry after n seconds
                time.sleep(n)
                continue
            raise
        except Exception as e:
            soup = BeautifulSoup(response.content, "html.parser")
            error_message = soup.find("div", class_="container").text.strip()
            if error_message == "Whoa there! You have exceeded a secondary rate limit. Please wait a few minutes before you try again; in some cases this may take up to an hour.":
                print(f"Rate limit exceeded: {error_message}")
                time.sleep(60 * (n + 1))  # Exponential backoff with a minimum of 1 minute
                continue
            raise

def classify_repositories(repositories):
    """Classifies repositories based on their descriptions using Google Generative AI in a single call.

    Args:
        repositories (list): A list of dictionaries containing repository data.

    Returns:
        dict: A dictionary containing all scraped repositories categorized by their descriptions.
    """

    if API_KEY is None:
        print("Please set API_KEY environment variable.")
        return {}  # Return empty dict if key isn't provided

    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    # Build the prompt with the full JSON structure and output format
    prompt = f"""
    You will be provided with a JSON structure representing GitHub repositories.
    Your task is to classify each repository into one of these categories:
    - **Finanzas**: Anything related to price APIs, banks, and similar things
    - **Mapas**: Postal Codes, City names, geographic data, etc
    - **Identificación**: Anything related to goverment ID (Cedula), passport, RIF, etc
    - **Comunidades**: Social network groups
    - **Paquetes**: Tech stack - specific software that is related to Venezuela, i.e: Odoo, wordpress, woocommerce, shopify, etc.
    - **Otros:** Anything else that doesn't fit into the above categories.

    You must return a JSON object in the following format:
    ```json
    {{
        "Finanzas": [
            {{ "link": "...", "description": "...", "stars": "..." }},
            {{ "link": "...", "description": "...", "stars": "..." }},
            ...
        ],
        "Mapas": [
            ...
        ],
        "Identificación": [
            ...
        ],
        "Comunidades": [
            ...
        ],
        "Paquetes": [
            ...
        ],
        "Otros": [
            ...
        ]
    }}
    ```

    Repositories:
    {json.dumps(repositories, indent=4)}
    """

    try:
        response = model.generate_content(prompt)
        response_text = response.text.strip()

        # Check for the code blocks and strip them
        if response_text.startswith("```json") and response_text.endswith("```"):
            response_text = response_text[7:-3].strip()

        # Now try parsing the response as JSON
        categorized_repositories = json.loads(response_text)
        return categorized_repositories
    except Exception as e:
        print(f"Google Generative AI request failed or returned invalid JSON: {e}")
        print(f"Raw Gemini response: {response_text}")
        return {}

def write_markdown(categorized_repositories, filename="README.md"):
    """Writes a markdown file with categorized repositories.

    Args:
        categorized_repositories (dict): A dictionary containing categorized repositories.
        filename (str, optional): The filename for the markdown file. Defaults to "awesome_venezuela.md".
    """

    with open(filename, "w") as f:
        f.write("# Awesome Venezuela\n")
        f.write("Recursos para desarrolladores ![made in VE](madeinve.svg) !\n\n")

        for category, repos in categorized_repositories.items():
            f.write(f"## {category}\n\n")
            for repo in repos:
                link = repo["link"]
                description = repo["description"]

                # Construct the markdown line with the desired badges
                f.write(f"- **[{link[1:]}](https://github.com{link})**{': '+description if description != link else ''} "
                        f"[![GitHub last commit](https://img.shields.io/github/last-commit/{link.split('/')[1]}/{link.split('/')[2]})]({link}) "
                        f"[![GitHub Repo stars](https://img.shields.io/github/stars/{link.split('/')[1]}/{link.split('/')[2]})]({link})\n\n")

def main():
    """Main function to scrape repositories and classify them."""

    query = "venezuela"
    repositories = []

    for page in range(1, 6):
        page_results = scrape_github_page(query, page)

        # Check if the first result has less than 10 stars
        if page_results and page_results[0]["stars"] < MIN_STARS:
            break

        repositories.extend(page_results)

    # Classify all repositories at once
    categorized_repositories = classify_repositories(repositories)

    print(json.dumps(categorized_repositories, indent=4))
    write_markdown(categorized_repositories)

if __name__ == "__main__":
    main()
