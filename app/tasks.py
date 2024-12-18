from app import celery, db
from app.models import Task
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import csv
import time
import urllib.parse
import os
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@celery.task(bind=True)
def process_csv(self, task_id):
    logger.info(f"Starting task {task_id}")
    task = Task.query.get(task_id)
    if not task:
        logger.error(f"Task {task_id} not found")
        return {'status': 'failed', 'message': 'Task not found'}
    
    try:
        # Update task status to processing
        task.status = 'PROCESSING'
        db.session.commit()
        logger.info(f"Task {task_id} status set to PROCESSING")
        
        # Read and deduplicate queries
        unique_queries = set()
        logger.info(f"Reading CSV file: {task.input_file}")
        with open(task.input_file, mode='r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                query_value = row.get('query', '').strip()
                if query_value:
                    unique_queries.add(query_value)

        unique_query_list = list(unique_queries)
        logger.info(f"Found {len(unique_query_list)} unique queries to process")
        
        # Update total items count
        task.total_items = len(unique_query_list)
        task.processed_items = 0
        db.session.commit()

        # Set up Selenium WebDriver
        logger.info("Initializing Chrome WebDriver")
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--start-maximized")
        driver = webdriver.Chrome(options=chrome_options)
        logger.info("Chrome WebDriver initialized successfully")

        query_competitors = {}
        
        for i, query in enumerate(unique_query_list):
            try:
                logger.info(f"Processing query {i+1}/{len(unique_query_list)}: {query}")
                encoded_query = urllib.parse.quote(query)
                url = f"https://www.google.com/search?q={encoded_query}"
                driver.get(url)
                logger.info(f"Loaded URL: {url}")
                time.sleep(2)

                competitor_elements = driver.find_elements(
                    By.CSS_SELECTOR, 
                    'div.rllt__details div[role="heading"] span.OSrXXb'
                )
                competitor_names = [el.text.strip() for el in competitor_elements]
                logger.info(f"Found {len(competitor_names)} competitors")

                if len(competitor_names) >= 3:
                    formatted_competitors = f"{competitor_names[0]}, {competitor_names[1]}, and {competitor_names[2]}"
                else:
                    formatted_competitors = ", ".join(competitor_names)

                query_competitors[query] = formatted_competitors
                logger.info(f"Competitors for '{query}': {formatted_competitors}")
                
                # Update progress
                task.processed_items = i + 1
                db.session.commit()
                logger.info(f"Progress updated: {i+1}/{len(unique_query_list)}")
                
                # Update Celery task state
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'current': i + 1,
                        'total': len(unique_query_list),
                        'status': f'Processing item {i + 1} of {len(unique_query_list)}'
                    }
                )
                
                time.sleep(10)
            
            except Exception as e:
                logger.error(f"Error processing query '{query}': {str(e)}")
                time.sleep(30)
                continue

        driver.quit()
        logger.info("Chrome WebDriver closed")

        # Write output CSV
        logger.info(f"Writing results to output file: {task.output_file}")
        with open(task.input_file, mode='r', newline='', encoding='utf-8') as infile, \
             open(task.output_file, mode='w', newline='', encoding='utf-8') as outfile:
            
            reader = csv.DictReader(infile)
            fieldnames = list(reader.fieldnames)
            if 'competitor' not in fieldnames:
                fieldnames.append('competitor')
            
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()
            
            # Reset file pointer
            infile.seek(0)
            next(reader)  # Skip header row

            rows_written = 0
            for row in reader:
                query_val = row.get('query', '').strip()
                if query_val in query_competitors:
                    row['competitor'] = query_competitors[query_val]
                writer.writerow(row)
                rows_written += 1
            
            logger.info(f"Wrote {rows_written} rows to output file")

        task.status = 'COMPLETED'
        task.completed_at = datetime.utcnow()
        db.session.commit()
        logger.info(f"Task {task_id} completed successfully")
        
        return {
            'status': 'success',
            'task_id': task_id,
            'total_items': task.total_items,
            'processed_items': task.processed_items
        }

    except Exception as e:
        logger.error(f"Task failed with error: {str(e)}")
        task.status = 'FAILED'
        db.session.commit()
        return {'status': 'failed', 'message': str(e)} 