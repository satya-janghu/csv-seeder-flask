from app import celery, db
from app.models import Task, QueryResult
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

def chunk_list(lst, chunk_size):
    """Split a list into smaller chunks"""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

@celery.task(bind=True)
def process_csv_chunked(self, task_id, chunk_size=50):
    task = Task.query.get(task_id)
    if not task:
        return {'status': 'failed', 'message': 'Task not found'}
    
    # Get queries to process
    unique_queries = set()
    with open(task.input_file, mode='r', newline='', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            query_value = row.get('query', '').strip()
            if query_value:
                unique_queries.add(query_value)
    
    # Split into chunks
    query_chunks = chunk_list(list(unique_queries), chunk_size)
    
    # Create subtasks for each chunk
    for chunk in query_chunks:
        process_csv.delay(task_id, chunk)
    
    return {'status': 'success', 'message': f'Split into {len(query_chunks)} subtasks'}

@celery.task(bind=True, soft_time_limit=3000, time_limit=3600)  # 50 min soft, 60 min hard limit
def process_csv(self, task_id):
    driver = None  # Initialize driver to None at the start
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
        
        # First check which queries we already have results for using SQLAlchemy 2.0 syntax
        stmt = db.select(QueryResult).where(QueryResult.query.in_(unique_queries))
        existing_results = {
            result.query: result.competitors 
            for result in db.session.execute(stmt).scalars().all()
        }
        
        # Filter out queries we already have results for
        queries_to_scrape = list(unique_queries - set(existing_results.keys()))
        logger.info(f"Found {len(existing_results)} existing results, "
                   f"need to scrape {len(queries_to_scrape)} new queries")
        
        task.total_items = len(queries_to_scrape)
        task.processed_items = 0
        db.session.commit()

        # Set up Selenium only if we have new queries to scrape
        query_competitors = {}
        if queries_to_scrape:
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    chrome_options = Options()
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("--start-maximized")
                    # Add these options for better stability
                    chrome_options.add_argument("--disable-gpu")
                    chrome_options.add_argument("--disable-software-rasterizer")
                    chrome_options.add_argument("--headless")  # Run in headless mode
                    
                    driver = webdriver.Chrome(options=chrome_options)
                    driver.set_page_load_timeout(30)  # 30 second timeout for page loads
                    
                    for i, query in enumerate(queries_to_scrape):
                        try:
                            logger.info(f"Processing query {i+1}/{len(queries_to_scrape)}: {query}")
                            
                            # Reset WebDriver every 50 queries to prevent memory issues
                            if i > 0 and i % 50 == 0:
                                driver.quit()
                                driver = webdriver.Chrome(options=chrome_options)
                                driver.set_page_load_timeout(30)
                            
                            encoded_query = urllib.parse.quote(query)
                            url = f"https://www.google.com/search?q={encoded_query}"
                            
                            # Add retry mechanism for page load
                            load_retries = 3
                            for attempt in range(load_retries):
                                try:
                                    driver.get(url)
                                    break
                                except Exception as e:
                                    if attempt == load_retries - 1:
                                        raise
                                    time.sleep(5 * (attempt + 1))
                            
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

                            # Store result in database
                            query_result = QueryResult(
                                query=query,
                                competitors=formatted_competitors
                            )
                            db.session.add(query_result)
                            db.session.commit()
                            
                            query_competitors[query] = formatted_competitors
                            
                            # Update progress
                            task.processed_items = i + 1
                            db.session.commit()
                            logger.info(f"Progress updated: {i+1}/{len(queries_to_scrape)}")
                            
                            # Update Celery task state
                            self.update_state(
                                state='PROGRESS',
                                meta={
                                    'current': i + 1,
                                    'total': len(queries_to_scrape),
                                    'status': f'Processing item {i + 1} of {len(queries_to_scrape)}'
                                }
                            )
                            
                            time.sleep(10)
                            
                            # Commit more frequently
                            if i % 10 == 0:
                                db.session.commit()
                            
                        except Exception as query_error:
                            logger.error(f"Error processing query '{query}': {str(query_error)}")
                            # Save progress
                            task.processed_items = i
                            db.session.commit()
                            
                            # If it's a session error, break the loop to restart the driver
                            if "invalid session id" in str(query_error).lower():
                                logger.info("Invalid session detected, restarting WebDriver...")
                                break
                            
                            time.sleep(30)
                            continue
                    
                    # If we got here without breaking, we're done
                    break
                    
                except Exception as e:
                    retry_count += 1
                    logger.error(f"WebDriver error (attempt {retry_count}/{max_retries}): {str(e)}")
                    if driver:
                        try:
                            driver.quit()
                        except:
                            pass
                    
                    if retry_count >= max_retries:
                        raise
                    
                    time.sleep(60)  # Wait before retrying
                
                finally:
                    if driver:
                        try:
                            driver.quit()
                        except:
                            pass

        # Combine new results with existing ones
        all_results = {**existing_results, **query_competitors}
        
        # Write complete output CSV
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
                if query_val in all_results:
                    row['competitor'] = all_results[query_val]
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
        task.error_message = str(e)
        db.session.commit()
        
        # Clean up WebDriver
        if driver:
            try:
                driver.quit()
            except:
                pass
        
        raise

    finally:
        # Make absolutely sure we clean up
        if driver:
            try:
                driver.quit()
            except:
                pass 