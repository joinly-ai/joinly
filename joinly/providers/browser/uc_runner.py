import undetected_chromedriver as uc
import sys
import json
import time

def main():
    if len(sys.argv) > 1:
        args = json.loads(sys.argv[1])
    else:
        args = []

    options = uc.ChromeOptions()
    for arg in args:
        options.add_argument(arg)
        
    driver = uc.Chrome(options=options)
    debugger_address = driver.capabilities['goog:chromeOptions']['debuggerAddress']
    
    # Print the format expected by browser_session.py
    print(f"DevTools listening on http://{debugger_address}", file=sys.stderr, flush=True)
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        driver.quit()

if __name__ == '__main__':
    main()
