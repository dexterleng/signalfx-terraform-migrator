import subprocess
from shared import *

DASHBOARD_PATH = './cms_summary.json'
DASHBOARD_GROUP_NAME='internal_tools'

def read_items():
  items = load_items(DASHBOARD_PATH)
  dashboard = list(filter(lambda i: i.get('sf_type') == 'Dashboard', items))[0]
  all_charts = list(filter(lambda i: i.get('sf_type') == 'Chart', items))
  all_items = [dashboard] + all_charts
  return (all_items, dashboard, all_charts)

def main():
  delete_state_files()

  items, dashboard, all_charts = read_items()

  # set dashboard attributes
  dashboard_mid = dashboard['marshallId']
  one_chart = all_charts[0]

  dashboard_id = one_chart['sf_dashboardId']
  dashboard['_id'] = dashboard_id

  insert_dashboard_attributes(dashboard, DASHBOARD_GROUP_NAME)

  # set chart attributes
  chart_resource_id_count = {}
  for chart in all_charts:
    # prevent chart id collision by adding _{nth_appearance} suffix to resource_id
    chart_name = f"{dashboard['_resource_id']}--{idify_name(chart['sf_chart'])}"
    if chart_name not in chart_resource_id_count:
      chart_resource_id_count[chart_name] = 0
    chart_resource_id_count[chart_name] += 1

    chart_resource_id = f'{chart_name}_{chart_resource_id_count[chart_name]}'
    if chart_resource_id_count[chart_name] == 1:
      chart_resource_id = chart_name 

    insert_chart_attributes(chart, chart_resource_id, dashboard)

  # create boilerplate file that is required to run `terraform import`
  create_boilerplate_for_terraform_import(items, './boilerplate.tf')

  subprocess.call(['terraform', 'init'])

  # import dashboards and chart state
  import_item_states(items, 3)

  # write state config to file
  subprocess.run(['mkdir', '-p', f'{DASHBOARD_GROUP_NAME}/'])

  with open(f"{DASHBOARD_GROUP_NAME}/{dashboard['_file_name']}.tf", 'w') as output_file:
    write_dashboard_to_file(dashboard, None, all_charts, output_file)
    for chart in all_charts:
      write_chart_to_file(chart, output_file)

  delete_state_files()

main()
