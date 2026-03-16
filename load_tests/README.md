# Load Testing

This directory contains scripts for load testing the Orchestra FastAPI server using [Locust](https://locust.io/).

## Prerequisites

- Install Locust: `pip install locust`
- Make sure the server dependencies are installed in your environment: `poetry install --extras "server"`

## Running the Test

1.  **Start the FastAPI Server:**
    From the project root, run the server. It needs to have the test graphs registered. The simplest way is to run the main app factory.

    ```sh
    poetry run uvicorn orchestra.server.app:create_app --factory
    ```

2.  **Run Locust:**
    Once the server is running, open a new terminal and run Locust.

    ```sh
    locust -f load_tests/locustfile.py --host http://127.0.0.1:8000
    ```

3.  **Start the Load Test:**
    Open your web browser to `http://localhost:8089` (the Locust web UI). Enter the number of users to simulate and the spawn rate, then start the test.

## Test Scenarios

- `locustfile.py`: A simple test that repeatedly calls the `POST /api/v1/runs` endpoint for a basic graph. This is useful for testing the baseline overhead of the run creation and execution process.
