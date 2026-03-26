"""
Setup script to create the onboarding_form.submissions table in BigQuery.
Run this once to create the table.

Usage:
    python setup_bigquery.py
"""

import time
from google.cloud import bigquery

PROJECT_ID = 'talent-demo-482004'
DATASET_ID = 'onboarding_form'
TABLE_ID = 'submissions'


def create_submissions_table():
    """Create the onboarding_form.submissions table in BigQuery."""

    client = bigquery.Client(project=PROJECT_ID)
    full_table_id = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

    # Create dataset if it doesn't exist
    dataset_ref = bigquery.Dataset(f"{PROJECT_ID}.{DATASET_ID}")
    dataset_ref.location = "US"
    try:
        client.get_dataset(dataset_ref)
        print(f"Dataset {DATASET_ID} already exists")
    except Exception:
        client.create_dataset(dataset_ref)
        print(f"Created dataset {DATASET_ID}")

    # Define schema
    schema = [
        # Submission identity
        bigquery.SchemaField("submission_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("submitted_at", "TIMESTAMP"),

        # Form fields from new hire
        bigquery.SchemaField("email", "STRING"),
        bigquery.SchemaField("first_name", "STRING"),
        bigquery.SchemaField("last_name", "STRING"),
        bigquery.SchemaField("preferred_name", "STRING"),
        bigquery.SchemaField("school_location", "STRING"),
        bigquery.SchemaField("phone", "STRING"),
        bigquery.SchemaField("physical_address", "STRING"),
        bigquery.SchemaField("tshirt_size", "STRING"),
        bigquery.SchemaField("dietary_needs", "STRING"),
        bigquery.SchemaField("food_allergies", "STRING"),
        bigquery.SchemaField("reading_certification", "STRING"),
        bigquery.SchemaField("numeracy_coursework", "STRING"),
        bigquery.SchemaField("ada_accommodation", "STRING"),

        # Admin-managed fields
        bigquery.SchemaField("onboarding_status", "STRING"),
        bigquery.SchemaField("start_date", "DATE"),
        bigquery.SchemaField("position_title", "STRING"),
        bigquery.SchemaField("badge_printed", "STRING"),
        bigquery.SchemaField("equipment_issued", "STRING"),
        bigquery.SchemaField("orientation_complete", "STRING"),
        bigquery.SchemaField("admin_notes", "STRING"),

        # Audit fields
        bigquery.SchemaField("updated_at", "TIMESTAMP"),
        bigquery.SchemaField("updated_by", "STRING"),
        bigquery.SchemaField("is_archived", "BOOL"),
    ]

    # Check if table already exists
    try:
        client.get_table(full_table_id)
        print(f"Table {full_table_id} already exists")
        return True
    except Exception:
        pass

    # Create table
    table = bigquery.Table(full_table_id, schema=schema)
    table = client.create_table(table)
    print(f"Created table {full_table_id}")

    # Wait for table to be available
    time.sleep(2)

    try:
        client.query(
            f"ALTER TABLE `{full_table_id}` ALTER COLUMN is_archived SET DEFAULT FALSE"
        ).result()
        print("Set default value for is_archived column")
    except Exception as e:
        print(f"Note: Could not set default for is_archived: {e}")

    print("\nSetup complete! You can now run the Onboarding Form app.")
    return True


if __name__ == "__main__":
    create_submissions_table()
