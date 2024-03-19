#!/usr/bin/python3.10

import sys
import os
from pyproj import Proj, transform, Transformer, CRS
import psycopg2
import psycopg2.extras
import geopy.distance
import math
# import fnt_sync
from pprint import pprint
import time
import json


# This is the most accurate i have found - based on 7 parameters conversion
mycrs = CRS.from_proj4("+proj=tmerc +lat_0=31.7343936111111 +lon_0=35.2045169444445 +k=1.0000067 +x_0=219529.584 +y_0=626907.39 +ellps=GRS80 +towgs84=-24.002400,-17.103200,-17.844400,-0.33077,-1.852690,1.669690,5.424800 +units=m +no_defs")
transformer = Transformer.from_crs(mycrs, 4326)

transformer_rev = Transformer.from_crs(4326, mycrs)



config = {

  'pgUser' : os.environ.get('PG_USER'),
  'pgPswd' : os.environ.get('PG_PSWD'),
  'pgName' : os.environ.get('PG_NAME'),
  'pgHost' : os.environ.get('PG_HOST'),
  'pgPort' : os.environ.get('PG_PORT'),

}

table_prefix = os.environ.get('TABLE_PREFIX')

listen_dir = os.getcwd() + '/spool/UPLOAD_QUEUE'

file_name = "./spool/data_iec.gdb"

ogr2ogr = f'''ogr2ogr -progress \
             -f "PostgreSQL" PG:"dbname={config['pgName']} host={config["pgHost"]} port={config["pgPort"]} user={config["pgUser"]} password={config["pgPswd"]}" \
             -overwrite -skipfailures --config PG_USE_COPY YES \
             -lco GEOMETRY_NAME=shape \
             -lco FID=objectid \
              '''


connection = None
  

def main():
  run_only_once = os.environ.get('RUN_ONLY_ONCE') == 'True'
  export_nodes = os.environ.get('EXPORT_NODES') == 'True'
  export_cables_trays = os.environ.get('EXPORT_CABLES_TRAYS') == 'True'
  export_splices = os.environ.get('EXPORT_SPLICES') == 'True'

  while True:
    change = False
    files = os.listdir(listen_dir)
    print(f"Found files: {files}")
    for file in files:
      print(file)

      print(ogr2ogr + './spool/UPLOAD_QUEUE/' + file)
      os.system(ogr2ogr + './spool/UPLOAD_QUEUE/' + file)
      os.system('mv ./spool/UPLOAD_QUEUE/' + file + ' ./spool/UPLOADED_FILES')
      change = True
    
    if change:
      geojson_file = [] 
      
      if export_nodes:
        geojson_file += iec_nodes_jb()

      if export_cables_trays:
        geojson_file += iec_cables_trays()

      if export_splices:
        geojson_file += iec_splices()
      
      if geojson_file:
        write_json(geojson_file, objectname='iec_features', dirname='./spool/OUTPUT_GEOJSON_FILES')
      
      print("Finish cycle.")

    if run_only_once:
      break
    else:
       time.sleep(60)



def write_json(features, objectname, dirname='.'):
    geojson_file = f"{dirname}/{objectname}.geojson"
    f = open(geojson_file,"w")
    f.write(json.dumps(features,indent=2))
    f.close()
    return geojson_file


def pgConnect():
    global connection
    connection = psycopg2.connect(user      = config['pgUser'],
                                  password  = config['pgPswd'],
                                  host      = config['pgHost'],
                                  port      = config['pgPort'],
                                  database  = config['pgName'])

def query(sql, first_run=True):
    global connection
    out = []
    if connection is None:
        pgConnect()
    try:
        cur = connection.cursor(cursor_factory = psycopg2.extras.RealDictCursor)
        cur.execute(sql)
        for row in cur:
            out.append( dict(row) )
        cur.close()

    except psycopg2.OperationalError as error:
        if first_run:
            pgConnect()
            return query(sql, False)
        else:
            return None, error

    except (Exception, psycopg2.DatabaseError) as error:
        connection.rollback()
        return None, error

    return out, None


def toWGS(x, y):
    if x >= 20 and x <= 60:
       # is already at WGS84
       return x, y


    if y < 360000:
        # is at ICS
        x += 50000
        y += 500000

    # is at ITM (2039)
    lat, lon = transformer.transform(x, y)
    return lon, lat


def distance(x1,y1,x2,y2):
    if x1 > 100000 and y1>300000 and x2 > 100000 and y2>300000:
        # ITM
        return math.sqrt( pow(x1-x2,2) + pow(y1-y2,2))
    else:
        return 10000000
        # print(f"distance for non itm {x1} {x2} {y1} {y2}")
        p1 = toWGS(x1,y1)
        p2 = toWGS(x2,y2)
        # print(f"distance for non itm {p1} {p2}")
        return geopy.distance.distance(p1, p2).m

def iec_pops():
  sql = """
    select name, locationdescription , "comments" , shape from iec_centraloffice ic
  """
  ret, err = query(sql)
  if err:
    print(err)
    sys.exit(0)
  for row in ret:
    # pprint(row)
    x, y = row['shape'].replace('POINT(','').replace(')','').split()




def iec_nodes_jb():

  nodeFeatures = []

  sql = """
    select objectid, locationid, ST_AsText(wkb_geometry::geometry) as shape, manholetype , "comments", status, datemodifier
    from fibermanhole if2
  """
  ret, err = query(sql)
  if err:
    print(err)
    sys.exit(0)
  for row in ret:
    x, y = row['shape'].replace('POINT(','').replace(')','').split()

    if row['comments'] is None:
      row['comments'] = ''
    if row['status'] is None:
      row['status'] = ''
    sf = {
            "_class": "node",
            "_type": f"MH_{row['manholetype']}",
            "_x": float(x),
            "_y": float(y),
            "_id": f"IEC-{row['objectid']}",
            "_visibleId": row['locationid'],
            "owner": "IEC",
            "origin": "Fibers-XML",
            "description" : row['comments']+'  '+row['status']
    }
    # pprint(sf)
    nodeFeatures.append(sf)


  sql = """
    select objectid, poleid, locationdescription , "comments", ST_AsText(wkb_geometry::geometry) as shape, splitters, datemodified , status
    from splicepoint is2
    where poleid is not null
  """
  poles = {}
  ret, err = query(sql)
  if err:
    print(err)
    sys.exit(0)
  for row in ret:
    x, y = row['shape'].replace('POINT(','').replace(')','').split()

    if row['poleid'] not in poles:
      poles[ row['poleid'] ] = row
    else:
      # pole id already exists
      print(f"Pole {row['poleid']} already exists")

      nx, ny = poles[ row['poleid'] ]['shape'].replace('POINT(','').replace(')','').split()
      d =  distance(float(x),float(y),float(nx),float(ny))
      if d<100:
        # close - take newer
        print(f"Pole is close {d}m - merging by more recent")
        if row['datemodified'] > poles[row['poleid']]['datemodified']:
          poles[ row['poleid'] ] = row
      else:
        print(f"Pole is far {d}m - new node named as objectid")
        # new row distance is larger than 100m - identify as new
        row['poleid'] = row['poleid'] + f" ({row['objectid']})"
        poles[ row['poleid'] ] = row

  statusMap = {
    '1':'קיים',
    '2':'מתוכנן',
    '3':'תקין',
    '4':'לביטול',
  }

  for poleId in poles:
    row = poles[poleId]
    x, y = row['shape'].replace('POINT(','').replace(')','').split()
    if row['comments'] is None:
      row['comments'] = ''
    if row['locationdescription'] is None:
      row['locationdescription'] = ''
    sf = {
            "_class": "node",
            "_type": "POLE",
            "_x": float(x),
            "_y": float(y),
            "_id": row['poleid'],
            "_visibleId": row['poleid'],
            "owner": "IEC",
            "origin": "Fibers-XML",
            "description" : row['locationdescription']+"\n"+row['comments']+"\n"+statusMap[row['status']]
    }
    # pprint(sf)
    nodeFeatures.append(sf)


    sf = {
            "_class": "junctionBox",
            "_type": "FIST_JBOX",
            "_id": f"JB-{row['poleid']}",
            "_visibleId": row['poleid'],
            "owner": "IEC",
            "_origin": "Fibers-XML",
            "_place": "node",
            "_nodeId": row['poleid']
    }
    # pprint(sf)
    nodeFeatures.append(sf)
  print(f'Found {len(nodeFeatures)} Nodes/JB')
  return nodeFeatures


def iec_cables_trays():

  trayFeatures = []

  sql = """
    select objectid, cablename, cabletype, fibercount , cablelength , undergroundoverhead , ST_AsText((ST_Dump(wkb_geometry::geometry)).geom) as shape
    from ohfibercable
  """
  ret, err = query(sql)
  if err:
    print(err)
    sys.exit(0)
  for row in ret:
    try:
      # Get Start/End points from Shape
      geom = []
      lineString = row['shape'].replace('LINESTRING(','').replace(')','').split(",")
      for pt in lineString:
        #pprint(row)
        parts = pt.split(" ")
        if len(parts)!=2:
           print(f"strange point: |{pt}|")
           continue
        x, y = parts[0], parts[1]
        geom.append( (float(x), float(y)) )
      #pprint(geom)

      if len(geom)==0:
        continue

      # x = geom[0][0]
      # y = geom[0][1]

      #n1 = findNodeAt(float(geom[0][0]), float(geom[0][1]))
      #n2 = findNodeAt(float(geom[-1][0]), float(geom[-1][1]))

      #if n1 is None:
      #  print(f"not found for {geom[0]}")
      #  a = input('ss')

      #if n1 != None and n2 != None:
      #  print(f"Found Edges {n1['ID']} {n2['ID']}")
        # Found Edges - Create Tray Section between Nodes
      trayType = 'TS_UNDER'
      if row['undergroundoverhead'] == 'Overhead':
        trayType = 'TS_OVER'
      sf = {
            "_class"          : "traySection",
            "_type"           : trayType,
            "geom"            : geom,
            "owner"           : "IEC",
            "origin"          : "Fibers-XML",
      }
      trayFeatures.append(sf)


      sf = {
          "_class"          : "cable",
          "_type"           : f"FO-{row['fibercount']}",
          "_origin"         : "Fibers-XML",
          "_id"             : row['cablename'],
          "_visibleid"      : row['cablename'],
          "owner"           : "IEC",
          "externalId"      : "",
          "n1"    : (float(geom[0][0]), float(geom[0][1])),
          "n2"      : (float(geom[-1][0]), float(geom[-1][1])),
          "_spare"          : { },
      }
      trayFeatures.append(sf)

    #except Exception as e:
    #  print(f"Exception Occurred: {e}")
    #  sys.exit(0)
    finally:
       pass
  print(f'Found {len(trayFeatures)} Trays/Cables') 
  return trayFeatures


def iec_splices():

  spliceFeatures = []

  sql = """
    select iff.traynumber , iff.splicetype, is2.poleid,
    cbl_a.cablename as cable1, tube_a.buffertubename as tube1, fiber_a.fibernumber as cable1fiber,
    cbl_b.cablename as cable2, tube_b.buffertubename as tube2, fiber_b.fibernumber as cable2fiber
    from f_fiberconnectionobject iff
    inner join splicepoint is2 on is2.globalid = iff.containerglobalid and iff.containerclassmodelname ='SPLICEPOINT'
    inner join f_fiber fiber_a on fiber_a.globalid = iff.aconnectionobjectglobalid
    inner join f_buffertube tube_a on tube_a.globalid = fiber_a.fiberparent
    inner join ohfibercable cbl_a on cbl_a.globalid = tube_a.fiberparent
    inner join f_fiber fiber_b on fiber_b.globalid = iff.bconnectionobjectglobalid
    inner join f_buffertube tube_b on tube_b.globalid = fiber_b.fiberparent
    inner join ohfibercable cbl_b on cbl_b.globalid = tube_b.fiberparent
    order by cbl_a.cablename , tube_a.buffertubename , fiber_a.fibernumber
  """

  ret, err = query(sql)
  if err:
    print(err)
  for row in ret:
    sf = {
      "_class"        : "splice",
      "_type"         : row['splicetype'],
      "_junctionBoxId": f"JB-{row['poleid']}",
      "_cable1"       : row['cable1'],
      "_cable1fiber"  : row['cable1fiber'],
      "_cable2"       : row['cable2'],
      "_cable2fiber"  : row['cable2fiber'],
      "_origin"       : 'Fibers-XML',
      "owner"         : 'IEC',
    }
    spliceFeatures.append(sf)
  print(f'Found {len(spliceFeatures)} Splices')
  return spliceFeatures


if __name__ == "__main__":
  main()
