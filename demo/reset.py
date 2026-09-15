#!/usr/bin/env python3
"""Reset by starting a fresh isolated run; never deletes a supplied path."""
from run import main

if __name__ == '__main__':
    print('RESET: allocating a new throwaway database.')
    main()
