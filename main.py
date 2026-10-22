"""Start the Student Attendance System.

    python main.py                  # data is kept in ./data
    python main.py --data-dir demo  # use another folder
"""

from attendance.gui.app import run

if __name__ == "__main__":
    run()
