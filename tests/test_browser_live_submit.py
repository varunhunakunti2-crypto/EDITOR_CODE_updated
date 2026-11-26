from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # 1. Register a fresh customer
    username = 'qa_submit_' + str(int(time.time()))
    page.goto('http://127.0.0.1:5000/register')
    page.fill('input[name=username]', username)
    page.fill('input[name=email]', username + '@test.local')
    page.fill('input[name=password]', 'pass123')
    page.select_option('select[name=role]', 'customer')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')

    # 2. Login
    page.goto('http://127.0.0.1:5000/login')
    page.fill('#username', username)
    page.fill('#password', 'pass123')
    page.click('button[type=submit]')
    page.wait_for_load_state('networkidle')

    # 3. Go to /design
    page.goto('http://127.0.0.1:5000/design')
    page.wait_for_load_state('networkidle')

    # 4. Fill form
    page.set_input_files('#imageInput', 'test.jpg')
    page.fill('#prompt', 'remove this monkey add red color dog')

    # 5. Click submit
    print('Submitting form...')
    t0 = time.time()
    page.click('#submitBtn', no_wait_after=True)

    page.wait_for_url('**/design/*', timeout=180000)
    print(f'Done! Successfully reached result in {round(time.time() - t0, 2)}s!')
    print('Final Result URL:', page.url)
    print('Headings:', page.locator('h1').all_text_contents())
    
    # Save a screenshot to verify!
    page.screenshot(path='docs/screenshots/live_result_verification.png', full_page=True)
    print('Saved docs/screenshots/live_result_verification.png')

    browser.close()
