import sys
import time
import requests
from requests.exceptions import HTTPError
from http import HTTPStatus
from bs4 import BeautifulSoup, Tag
import os
import json
from google import genai
from pydantic import BaseModel, Field
from typing import List

# Replace with your actual Google Cloud API Key
API_KEY = os.environ.get("API_KEY")
MIN_STARS = 20

EXCLUDED_USERS = ["nesttyy"]  # Add more users to this list if needed

class Repository(BaseModel):
    link: str
    description: str

class CategorizedRepositories(BaseModel):
    Finanzas: List[Repository] = Field(default_factory=list)
    Mapas: List[Repository] = Field(default_factory=list)
    Identificación: List[Repository] = Field(default_factory=list)
    Comunidades: List[Repository] = Field(default_factory=list)
    Paquetes: List[Repository] = Field(default_factory=list)
    E_commerce: List[Repository] = Field(default_factory=list, alias="E-commerce")
    Gobierno: List[Repository] = Field(default_factory=list)
    Utilidades: List[Repository] = Field(default_factory=list)
    Educación: List[Repository] = Field(default_factory=list)
    Salud: List[Repository] = Field(default_factory=list)
    Otros: List[Repository] = Field(default_factory=list)

    class Config:
        populate_by_name = True

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
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
            response = requests.get(url, headers=headers)
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
            if code in retry_codes:
                time.sleep(n + 1)
                continue
            raise
        except Exception as e:
            soup = BeautifulSoup(response.content, "html.parser")
            error_msg_div = soup.find("div", class_="container")
            if error_msg_div:
                error_message = error_msg_div.text.strip()
                if "exceeded a secondary rate limit" in error_message:
                    print(f"Rate limit exceeded: {error_message}")
                    time.sleep(60 * (n + 1))
                    continue
            raise

def classify_repositories(repositories):
    """Classifies repositories based on their descriptions using Google Generative AI."""

    if API_KEY is None:
        print("Please set API_KEY environment variable.")
        return {}

    client = genai.Client(api_key=API_KEY)
    model_id = "gemini-3-flash-preview"

    prompt = f"""
    You will be provided with a JSON structure representing GitHub repositories.
    Your task is to classify each repository into one of these categories:
    - **Finanzas**: Anything related to price APIs, banks, and similar things.
    - **Mapas**: Postal Codes, City names, geographic data, etc.
    - **Identificación**: Anything related to government ID (Cedula), passport, RIF, etc.
    - **Comunidades**: Social network groups.
    - **Paquetes**: Tech stack - specific software that is related to Venezuela, i.e: Odoo, wordpress, woocommerce, shopify, etc.
    - **E-commerce**: Delivery platform integrations, shipping tracking (MRW, Tealca, Zoom), local payment gateways.
    - **Gobierno**: Election results, census data, public observatories, and transparency tools.
    - **Utilidades**: Browser extensions, developer CLI tools, and productivity scripts.
    - **Educación**: University resources, academic archives, and cultural preservation projects.
    - **Salud**: Pharmacy stock trackers, medical directories, or public health data.
    - **Otros:** Anything else that doesn't fit into the above categories.

    You must return a JSON object where each category is a list of objects. Each object MUST have a "link" and "description" field.
    Use the exact "link" and "description" provided in the Input JSON.

    Input JSON:
    {json.dumps(repositories, indent=4)}
    """

    for attempt in range(3):
        try:
            time.sleep(1 + attempt * 2)
            response = client.models.generate_content(
                model=model_id,
                contents=prompt,
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': CategorizedRepositories,
                }
            )
            # The SDK returns the parsed response when response_schema is provided
            return response.parsed.model_dump()
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                return {}
    return {}

def write_markdown(categorized_repositories, filename="README.md"):
    """Writes a markdown file with categorized repositories."""

    with open(filename, "w") as f:
        f.write("# Awesome Venezuela\n")
        f.write("Recursos para desarrolladores ![made in VE](madeinve.svg) !\n\n")

        for category, repos in categorized_repositories.items():
            if not repos:
                continue
            f.write(f"## {category}\n\n")
            for repo in repos:
                if isinstance(repo, dict):
                    link = repo.get("link", "")
                    description = repo.get("description", link)
                else:
                    link = str(repo)
                    description = link

                if not link:
                    continue

                f.write(f"- **[{link[1:]}](https://github.com{link})**{': '+description if description != link else ''} "
                        f"[![GitHub last commit](https://img.shields.io/github/last-commit/{link.split('/')[1]}/{link.split('/')[2]})]({link}) "
                        f"[![GitHub Repo stars](https://img.shields.io/github/stars/{link.split('/')[1]}/{link.split('/')[2]})]({link})\n\n")

def main():
    """Main function to scrape repositories and classify them."""

    query = "venezuela"
    repositories = []

    for page in range(1, 6):
        page_results = scrape_github_page(query, page)
        if not page_results:
            break
        if page_results[0]["stars"] < MIN_STARS:
            repositories.extend([r for r in page_results if r["stars"] >= MIN_STARS])
            break
        repositories.extend(page_results)

    categorized_repositories = classify_repositories(repositories)
    print(json.dumps(categorized_repositories, indent=4))
    write_markdown(categorized_repositories)

if __name__ == "__main__":
    main()
