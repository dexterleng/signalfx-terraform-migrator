import json
import subprocess
import re

signalfx_export_path = './kcp_ingestion_dashboard.json'

def load_items(path):
  file = open(path, 'r')
  result = json.load(file)
  file.close()
  return result

def assert_item_type(item, _type):
  assert item['sf_type'] == _type

def idify_name(name):
  return name.lower().strip().replace(' ', '_').replace('(', '').replace(')', '')

def map_chart_to_resource_type(chart):
  chart_type = chart['sf_visualizationOptions']['type']
  # Incomplete!
  table = {
    'SingleValue': 'signalfx_single_value_chart',
    'TimeSeriesChart': 'signalfx_time_chart',
  }
  return table[chart_type]

def insert_dashboard_attributes(dashboard, any_chart):
  dashboard['_resource_type'] = 'signalfx_dashboard'
  dashboard['_resource_id'] = idify_name(dashboard['sf_dashboard'])
  dashboard['_resource_type_id'] = f"{dashboard['_resource_type']}.{dashboard['_resource_id']}"
  dashboard['_id'] = any_chart['sf_dashboardId']

def insert_chart_attributes(chart, resource_id, dashboard):
  chart['_resource_type'] = map_chart_to_resource_type(chart)
  chart['_resource_id'] = resource_id
  chart['_resource_type_id'] = f"{chart['_resource_type']}.{chart['_resource_id']}"

  # chart id can only be found in the dashboard :/
  associated_dashboard_widget = list(filter(lambda w: w['options']['chartIndex'] == chart['sf_chartIndex'], dashboard['sf_uiModel']['widgets']))[0]
  
  chart_id = associated_dashboard_widget['options']['chartId']
  chart["_id"] = chart_id


def boilerplate_for_item(item):
  # double curly escapes for f-strings https://stackoverflow.com/a/42521252/10390454
  return f"""
resource "{item['_resource_type']}" "{item['_resource_id']}" {{
}}
"""

def create_boilerplate_for_terraform_import(dashboard, charts, out):
  with open(out, 'w') as boilerplate_file:
    boilerplate_file.write(
"""
provider "signalfx" {
  auth_token = var.signalfx_auth_token
  api_url = var.signalfx_api_url
}

variable "signalfx_auth_token" {
  type = string
}

variable "signalfx_api_url" {
  type = string
}

"""
)

    boilerplate_file.write(
      boilerplate_for_item(dashboard)
    )

    for chart in charts:
      boilerplate_file.write(
        boilerplate_for_item(chart)
      )

def import_item_state_from_terraform(item):
  p = subprocess.run(f"terraform import {item['_resource_type_id']} {item['_id']}", shell=True, stderr=subprocess.PIPE)
  print(p.stderr.decode())

def show_state_of_item(item):
  p = subprocess.run(f"terraform state show {item['_resource_type_id']}", shell=True, stdout=subprocess.PIPE)
  return p.stdout.decode()

def delete_state_files():
  subprocess.call(['rm', '-rf', '.terraform'])
  subprocess.call(['rm', '-f', 'terraform.tfstate'])
  subprocess.call(['rm', '-rf', 'terraform.tfstate.backup'])

def replace_signalfx_id_with_terraform_identifier(string, resource_type_id_by_signalfx_id_map):
  for sf_id in resource_type_id_by_signalfx_id_map:
    resource_type_id = resource_type_id_by_signalfx_id_map[sf_id]
    string = string.replace(f'"{sf_id}"', f'{resource_type_id}.id')
  return string

def write_item_state_to_file(item, f, resource_type_id_by_signalfx_id_map):
  ansi_escape = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')
  remove_id_attr = re.compile(r'^ *id *=.*$\n', re.MULTILINE)
  remove_url_attr = re.compile(r'^ *url *=.*$\n', re.MULTILINE)
  eot_start = re.compile(r'<<~EOT', re.MULTILINE)
  eot_end = re.compile(r'EOT', re.MULTILINE)

  o = show_state_of_item(item)
  o = ansi_escape.sub('', o)
  o = remove_id_attr.sub('', o)
  o = remove_url_attr.sub('', o)
  o = eot_start.sub('<<-EOF', o)
  o = eot_end.sub('EOF', o)
  o = replace_signalfx_id_with_terraform_identifier(o, resource_type_id_by_signalfx_id_map)

  f.write(o)
  f.write('\n')

def main():
  delete_state_files()

  items = load_items(signalfx_export_path)
  dashboard = list(filter(lambda i: i.get('sf_type') == 'Dashboard', items))[0]
  charts = list(filter(lambda i: i.get('sf_type') == 'Chart', items))

  # insert dashboard attributes
  insert_dashboard_attributes(dashboard, charts[0])

  # insert chart attributes
  chart_resource_id_count = {}
  for chart in charts:
    # prevent chart id collision by adding _{nth_appearance} suffix to resource_id
    chart_name = idify_name(chart['sf_chart'])
    if chart_name not in chart_resource_id_count:
      chart_resource_id_count[chart_name] = 0
    chart_resource_id_count[chart_name] += 1

    chart_resource_id = f'{chart_name}_{chart_resource_id_count[chart_name]}'
    if chart_resource_id_count[chart_name] == 1:
      chart_resource_id = chart_name

    insert_chart_attributes(chart, chart_resource_id, dashboard)

  # create boilerplate file that is required to run `terraform import`
  create_boilerplate_for_terraform_import(dashboard, charts, './boilerplate.tf')

  subprocess.call(['terraform', 'init'])

  # import dashboard and chart state
  import_item_state_from_terraform(dashboard)
  for chart in charts:
    import_item_state_from_terraform(chart)

  # build map of signalfx id -> resource type . resource name
  resource_type_id_by_signalfx_id_map = {}
  resource_type_id_by_signalfx_id_map[dashboard['_id']] = dashboard['_resource_type_id']
  for chart in charts:
    resource_type_id_by_signalfx_id_map[chart['_id']] = chart['_resource_type_id']

  # write state config to file
  subprocess.run(['mkdir', '-p', 'output/'])
  with open('output/output.tf', 'w') as output_file:
    write_item_state_to_file(dashboard, output_file, resource_type_id_by_signalfx_id_map)  
    for chart in charts:
      write_item_state_to_file(chart, output_file, resource_type_id_by_signalfx_id_map)
  
  # map_json = json.dumps(resource_type_id_by_signalfx_id_map)
  # with open('output/id_map.json', 'w') as output_file:
  #   output_file.write(map_json)

  # delete state file to prevent someone from accidentally deploying this
  delete_state_files()

main()
