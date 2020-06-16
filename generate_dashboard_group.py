import subprocess
from shared import *

DASHBOARD_GROUP_PATH = './internal_tools.json'
DASHBOARD_GROUP_NAME='internal_tools'
DB_GROUP_ID = 'C_X_h_xAcAA'

def read_items():
  items = load_items(DASHBOARD_GROUP_PATH)
  dashboard_group = list(filter(lambda i: i.get('sf_type') == 'Page', items))[0]
  all_dashboards = list(filter(lambda i: i.get('sf_type') == 'Dashboard', items))
  all_charts = list(filter(lambda i: i.get('sf_type') == 'Chart', items))
  all_items = [dashboard_group] + all_dashboards + all_charts
  return (all_items, dashboard_group, all_dashboards, all_charts)

def insert_dashboard_group_attributes(dashboard_group):
  dashboard_group['_resource_type'] = 'signalfx_dashboard_group'
  dashboard_group['_resource_id'] = DASHBOARD_GROUP_NAME
  dashboard_group['_resource_type_id'] = f"{dashboard_group['_resource_type']}.{dashboard_group['_resource_id']}"
  dashboard_group['_file_name'] = f"{DASHBOARD_GROUP_NAME}_dashboard_group"

def main():
  delete_state_files()

  items, dashboard_group, all_dashboards, all_charts = read_items()

  marshall_id_to_children_map = build_mid_to_children_map([dashboard_group] + all_dashboards + all_charts)

  insert_dashboard_group_attributes(dashboard_group)
  dashboard_group['_id'] = DB_GROUP_ID

  # set dashboard attributes
  for dashboard in all_dashboards:
    dashboard_mid = dashboard['marshallId']
    one_chart = marshall_id_to_children_map[dashboard_mid][0]

    dashboard_id = one_chart['sf_dashboardId']
    dashboard['_id'] = dashboard_id

    insert_dashboard_attributes(dashboard, DASHBOARD_GROUP_NAME)

  # set chart attributes
  chart_resource_id_count = {}
  for dashboard in all_dashboards:
    dashboard_mid = dashboard['marshallId']

    for chart in marshall_id_to_children_map[dashboard_mid]:
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
  create_boilerplate_for_terraform_import([dashboard_group] + all_dashboards + all_charts, './boilerplate.tf')

  subprocess.call(['terraform', 'init'])

  # import dashboards and chart state
  import_item_states([dashboard_group] + all_dashboards + all_charts, 3)

  # write state config to file
  subprocess.run(['mkdir', '-p', f'{DASHBOARD_GROUP_NAME}/'])

  with open(f"{DASHBOARD_GROUP_NAME}/{dashboard_group['_file_name']}.tf", 'w') as output_file:
    write_dashboard_group_to_file(dashboard_group, output_file)

  for i in range(len(all_dashboards)):
    dashboard = all_dashboards[i]
    dashboard_mid = dashboard['marshallId']
    charts = marshall_id_to_children_map[dashboard_mid]

    with open(f"{DASHBOARD_GROUP_NAME}/{dashboard['_file_name']}.tf", 'w') as output_file:
      write_dashboard_to_file(dashboard, dashboard_group, charts, output_file)
      for chart in charts:
        write_chart_to_file(chart, output_file)

  delete_state_files()

main()
