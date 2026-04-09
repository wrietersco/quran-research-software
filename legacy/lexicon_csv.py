import json
import csv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

# JSON file path
json_file_path = 'quran_data.json'
csv_file_path = 'quran_data.csv'

# Website URL
website_url = "https://lexicon.quranic-research.net/data/01_A/000_A.html"

# Set up ChromeDriver options
options = Options()
options.add_argument("--headless")  # Run in headless mode (comment out for visible browser)
options.add_argument("--disable-gpu")

# Initialize ChromeDriver
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# Navigate to the website
driver.get(website_url)

data = []
with open(csv_file_path, 'w', newline='', encoding='utf-8') as csv_file:
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["Root Word", "Main Entry", "Entry Definition"])

    while True:
        try:
            # Wait for page to load
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "article.root"))
            )

            # Get root word
            root_word_element = driver.find_element(By.CSS_SELECTOR, "article.root > h2.root")
            root_word = root_word_element.text

            # Initialize main entries list
            main_entries = []

            # Get all sections with class "entry main"
            sections = driver.find_elements(By.CSS_SELECTOR, ".entry.main")


            for section in sections:
                # Click the section
                section.click()

                # Check if child with class "visible" exists
                visible_child = section.find_elements(By.CSS_SELECTOR, ".visible")
                if visible_child:
                    # Wait for main entry element to be visible
                    main_entry_element = WebDriverWait(driver, 10).until(
                        EC.visibility_of_element_located((By.CSS_SELECTOR, "h3.entry"))
                    )
                    
                    # Get main entry
                    main_entry_text = main_entry_element.text

                    # Get entry definition
                    entry_definition = section.text.replace(main_entry_text, '').strip()

                    # Add main entry to list
                    main_entries.append({main_entry_text: entry_definition})

                    # Write data to CSV file
                    csv_writer.writerow([root_word, main_entry_text, entry_definition])

            # Create data object
            # data_object = {
            #     "root word": root_word,
            #     "main entries": main_entries
            # }

            # Append data object to data list
            # data.append(data_object)

            # Save data to JSON file
            # with open(json_file_path, 'w', encoding='utf-8') as json_file:
            #     json.dump(data, json_file, indent=4, ensure_ascii=False)

            # print(f"Appended data to JSON and CSV files")

            # Click the next button
            next_button = driver.find_element(By.CLASS_NAME, "next")
            next_button.click()

        except Exception as e:
            print(f"Error occurred: {e}")
            break

# Close the browser
driver.quit()