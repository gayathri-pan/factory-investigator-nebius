"""Copy six historical tables into the new project; source tables are read-only."""
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

PROJECT = 'factory-investigator-nebius'
SOURCE = 'project-e64210d0-f317-4050-833.factory_ai_investigator'
DESTINATION = PROJECT + '.factory_ai_investigator'
TABLES = ['factory_machines','sensors','machine_logs','maintenance_history','historical_incidents','anomaly_events']


def main():
    with bigquery.Client(project=PROJECT,location='asia-south1') as client:
        try:
            destination = client.get_dataset(DESTINATION)
        except NotFound:
            destination = bigquery.Dataset(DESTINATION)
            destination.location = 'asia-south1'
            destination = client.create_dataset(destination)
        if destination.location.lower() != 'asia-south1':
            raise RuntimeError('Destination must be in asia-south1.')
        for name in TABLES:
            target = DESTINATION + '.' + name
            try:
                existing = client.get_table(target)
                print('Existing table retained:',target,'rows:',existing.num_rows)
            except NotFound:
                config = bigquery.CopyJobConfig(write_disposition='WRITE_EMPTY')
                client.copy_table(SOURCE+'.'+name,target,job_config=config,location='asia-south1').result()
                print('Copied:',target,'rows:',client.get_table(target).num_rows)
        # API can read only this new dataset; it does not write operational tables.
        destination = client.get_dataset(DESTINATION)
        entry = bigquery.AccessEntry('READER','userByEmail',f'nebius-dashboard@{PROJECT}.iam.gserviceaccount.com')
        entries = list(destination.access_entries)
        if entry not in entries:
            destination.access_entries = entries + [entry]
            client.update_dataset(destination,['access_entries'])
        print('Historical copy and new API dataset-read access: complete.')


if __name__ == '__main__':
    main()
