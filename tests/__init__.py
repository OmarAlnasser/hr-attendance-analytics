import logging

# Access-denied warnings are expected in the permission tests; keep the test output readable.
logging.getLogger("hr_analytics.web").setLevel(logging.ERROR)
