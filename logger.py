# ============================================================================
# LOGGING CONFIGURATION FOR NIFTY INTRADAY OPTION SELLING STRATEGY
# ============================================================================

import logging
import sys
from datetime import datetime
from io import TextIOWrapper

# Configure logging
current_date = datetime.now().strftime('%Y-%m-%d')
log_filename = f'Nifty_Intraday_Option_Selling_{current_date}.log'

# Set up logging format
log_format = '%(asctime)s | %(levelname)s | %(message)s'
date_format = '%Y-%m-%d %H:%M:%S'

# Configure logger
stdout_stream = sys.stdout.buffer if hasattr(sys.stdout, 'buffer') else sys.stdout
utf8_stdout = TextIOWrapper(stdout_stream, encoding='utf-8', errors='replace', line_buffering=True)
stream_handler = logging.StreamHandler(utf8_stdout)

logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    datefmt=date_format,
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        stream_handler
    ]
)

logger = logging.getLogger(__name__)
