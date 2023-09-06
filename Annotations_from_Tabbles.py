import omero
from omero.model import TagAnnotationI
from omero.gateway import BlitzGateway
from omero.rtypes import rstring, rlong
import omero.scripts as scripts
from omero.cmd import Delete2
import xml.etree.ElementTree as ET
import ast

import re
import pyodbc
import json
import pandas as pd

DEFAULT_NAMESPACE = omero.constants.metadata.NSCLIENTMAPANNOTATION

def get_existing_map_annotations(image):
    """Get all Map Annotations linked to the object

    Parameters:
    --------------
    image: ``omero.model.ImageI`` object
        the image from which the MapAnnoations are to be retrieved
    
    Returns:
    -------------
    existing: dict
        MapAnnotations in the format of {namespace1:{key1:['value1','value2', ...], key2: ...}, namespace2: ...}
    """
    existing = {}
    for annotation in image.listAnnotations():
        if isinstance(annotation, omero.gateway.MapAnnotationWrapper):
            namespace = annotation.getNs()
            if namespace not in existing:
                existing[namespace] = {}
            key_values = annotation.getValue()
            for key, value in key_values:
                if key not in existing[namespace]:
                    existing[namespace][key] = []
                existing[namespace][key].append(value)
    return existing

def get_tag_dict(conn):
    """Gets a dict of all existing Tag Names with their respective OMERO IDs as values

    Parameters:
    --------------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
 
    Returns:
    -------------
    tag_dict: dict
        Dictionary in the format {tag1.name:tag1.id, tag2.name:tag2.id, ...}
    """
    meta = conn.getMetadataService()
    taglist = meta.loadSpecifiedAnnotations("TagAnnotation","","",None)
    tag_dict = {}
    for tag in taglist:
        name = tag.getTextValue().getValue()
        tag_id = tag.getId().getValue()
        if name not in tag_dict:
            tag_dict[name] = tag_id
    return tag_dict

def get_linked_tag_annotations(image):
    """Get all Tag Annotations linked to the object

    Parameters:
    --------------
    image: ``omero.model.ImageI`` object
        the image from which all TagAnnotations are to be retrieved 

    Returns:
    -------------
    existing: list
        List of strings with the Tag names
    """
    existing = []
    for ann in image.listAnnotations():
        if isinstance(ann, omero.gateway.TagAnnotationWrapper):
            value = ann.getValue()
            existing.append(value)
    return existing

def remove_map_annotations(conn, image, namespace):
    """Remove MapAnnotations matching a given Namespace from the image

    Parameters:
    --------------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    image: ``omero.model.ImageI`` object
        the image from which the MapAnnotations are to be removed
    namespace: string
        the Namespace of the MapAnnotations which are to be removed
    """
    annotations = list(image.listAnnotations())
    mapann_ids = [ann.id for ann in annotations
                  if isinstance(ann, omero.gateway.MapAnnotationWrapper) and ann.getNs()==namespace]

    try:
        delete = Delete2(targetObjects={'MapAnnotation': mapann_ids})
        handle = conn.c.sf.submit(delete)
        conn.c.waitOnCmd(handle, loops=10, ms=500, failonerror=True,
                         failontimeout=False, closehandle=False)

    except Exception as ex:
        print("Failed to delete links: {}".format(ex.message))
    

def remove_tag_annotations(conn, image):
    """Remove ALL Tag Annotations on the object and returns the number of deleted Tag Annotations
    Parameters:
    --------------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    image: ``omero.model.ImageI`` object
        the image from which the tags are to be removed
    
    Returns:
    -------------
    number_of_deleted_tags: int
        the total amount of deleted tags
    """
    number_of_deleted_tags = 0
    imageId = image.getId()
    # get all TagAnnotations of the Image
    annotations = list(image.listAnnotations())
    if not len(annotations) >= 0:
        return
    tagAnnotations = [ann for ann in annotations
                  if isinstance(ann, omero.gateway.TagAnnotationWrapper)]
    
    # get the AnnotationLinks and delete them
    for tagAnnotation in tagAnnotations:
        links = tagAnnotation.getParentLinks("Image",[imageId])
        for link in links:
            conn.deleteObject(link._obj)
            number_of_deleted_tags+=1
            print("Unlinked Tag ", tagAnnotation.getValue())
    
    # try:
    #     delete = Delete2(targetObjects={'TagAnnotation': tagann_ids})
    #     handle = conn.c.sf.submit(delete)
    #     conn.c.waitOnCmd(handle, loops=10, ms=500, failonerror=True,
    #                      failontimeout=False, closehandle=False)

    # except Exception as ex:
    #     print("Failed to delete links: {}".format(ex.message))
    return number_of_deleted_tags

def getMaprNamespaces():
    '''Extracts defined OMERO.mapr Namespaces from the omero-web config as a list of strings.
    Also acts as a pseudo-check if OMERO.mapr is configured on the system.
    
    Returns:
    -------------
    namespaces: list
        List of OMERO.mapr-defined Namespaces as strings
    '''
    # omero-web config path from default location
    path = r"/opt/omero/omero-web/etc/grid/config.xml"
    # parse the xml into a dictionary
    tree = ET.parse(path)
    root = tree.getroot()
    for prop in root[0].iter("property"):
        if prop.attrib['name']=='omero.web.mapr.config':
            raw = prop.attrib['value'].replace("true","True")
            mapr = ast.literal_eval(raw)

    namespaces = []
    # loop over the dict and get all defined Namespaces
    for m in mapr:
        # check if there even is a string in the list or just an empty Namespace
        if len(m["config"]["ns"])>0:
            namespaces.append(m["config"]["ns"][0])
    
    return namespaces

def transformToMaprNamespace(orig_ns):
    '''Create the defined OMERO.mapr Namespace from the Tabbles Namespace
    Parameters:
    --------------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    script_params: dict
        Script Parameters derived from User input
    
    Returns:
    -------------
    images: list
        List of Images as ``omero.model.ImageI`` objects
    '''
    mapr_ns_list = getMaprNamespaces()
    # extract only the letter-wise namespace (e.g. "01_Biosample" becomes "biosample")
    only_letters_ns = re.search(r"[a-zA-Z\s]{3,}",orig_ns).group()

    # if the letter-wise namespace is contained in the OMERO.mapr Namespaces return the
    # respective Namespace
    result=""
    for namespace in mapr_ns_list:
        # check if the regex.search found anything and compare it to the defined namespaces
        if only_letters_ns!=None and only_letters_ns.lower() in namespace.lower():
            result = namespace
            print("transformed Namespace: ",result)
    return result



def getImages(conn, script_params):
    '''Gets a list of all Images from a (list) of Project(s)/Dataset(s)/Image(s)

    Parameters:
    --------------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    script_params: dict
        Script Parameters derived from User input
    
    Returns:
    -------------
    images: list
        List of Images as ``omero.model.ImageI`` objects
    
    '''
    images = []
    
    if script_params["Data_Type"]=="Dataset":
        datasets = conn.getObjects("Dataset",script_params["IDs"])
        for ds in datasets:
            dataset_images = list(ds.listChildren())
            for img in dataset_images:
                images.append(img)
                
    elif script_params["Data_Type"]=="Image":
        for id in script_params["IDs"]:
            img = conn.getObject("Image",id)
            images.append(img)

    elif script_params["Data_Type"]=="Project":
        projects = conn.getObjects("Project",script_params["IDs"])
        datasets = []
        for project in projects:
            project_datasets = list(project.listChildren())
            for ds in project_datasets:
                datasets.append(ds)
        for ds in datasets:
            dataset_images = list(ds.listChildren())
            for img in dataset_images:
                images.append(img)

    return images

def getData(image, script_params):
    '''Gets Data for one Image from the Microsoft SQL Server that Tabbles uses
    Parameters:
    --------------
    image : ``omero.model.ImageI`` object
        the image in question
    script_params: dict
        Script Parameters derived from User input
    
    Returns:
    -------------
    tabbles_data: dict
        Data derived from tabbles {namespace:{key:['value1','value2', ...], key2: ...}, namespace2: ...}
    '''
    # always take first path, assuming that for file formats which have multiple file paths
    # (e.g. Olympus ScanR HCS) the Tags stay same for the whole Fileset
    raw_path = image.getImportedImageFilePaths()['client_paths'][0]
    cleaned_path = raw_path.replace(";",":") # getting rid of the pesky "C;/../.." path format of OMERO
    final_path = cleaned_path.replace("/","\\")

    # connect to tabbles DB
    cnxn_str = ('DRIVER='+DRIVER+';SERVER='+SERVER+';DATABASE='+DATABASE+';UID='+USERNAME+';PWD='+PWD+';TrustServerCertificate=yes')
    cnxn = pyodbc.connect(cnxn_str)
    print("connected to MSSQL server")
    cursor = cnxn.cursor()

    database = script_params["Tabbles_Database"]
    # the raw SQL query
    query=(rf"""
    SELECT distinct TAG3.name as namespace_, TAG2.name as key_, TAG1.name as value_
    FROM [{database}].[dbo].[file2] files
    INNER JOIN [{database}].[dbo].[taggable_has_tag]
    ON (files.[idTaggable] = [{database}].[dbo].[taggable_has_tag].id_taggable)
    INNER JOIN [{database}].[dbo].[tag] TAG1
    ON (TAG1.id = [{database}].[dbo].[taggable_has_tag].id_tag)
    LEFT JOIN [{database}].[dbo].[tabble_is_child_of_tag_for_user] CHILD1
    ON (CHILD1.id_tabble_child=TAG1.id_tabble)
    LEFT JOIN [{database}].[dbo].[tag] TAG2
    ON (TAG2.id=CHILD1.id_tag_parent)
    LEFT JOIN [{database}].[dbo].[tabble_is_child_of_tag_for_user] CHILD2
    ON (CHILD2.id_tabble_child=TAG2.id_tabble)
    LEFT JOIN [{database}].[dbo].[tag] TAG3
    ON (TAG3.id=CHILD2.id_tag_parent)
    WHERE files.path LIKE '{final_path}'
    """)
    print("querystring ends with ",query[query.index("LIKE"):])

    # Execute the query
    cursor.execute(query)
    # get all the lines
    raw_list = cursor.fetchall()

    # create a pandas DataFrame from the raw_list to get rid of duplicate entries (when namespace/parent tag = "_workspace...")
    raw_df = pd.DataFrame.from_records(raw_list)
    duplicates_removed_df = raw_df.drop_duplicates(subset=[1,2],keep="last") #"last" as the namespaces are ordered by alphabet

    # generate a dict of namespace-level tags with dicts of key-level tags containing a list of value-level strings
    # Iterate over each row in the dataframe
    tabbles_data={}
    for _, row in duplicates_removed_df.iterrows():
        namespace = row[0]
        key = row[1]
        value = row[2]
        # Create nested dictionaries if they don't exist
        if namespace not in tabbles_data:
            tabbles_data[namespace] = {}
        if key not in tabbles_data[namespace]:
            tabbles_data[namespace][key] = []
        # Append the value to the list of values
        tabbles_data[namespace][key].append(value)
        
    return tabbles_data

def split_data(script_params, data_dict):
    '''Splits the data dictionary that comes from Tabbles into the relevant formats for MapAnnotations and TagAnnotations
    respecting the script parameters.
    Parameters:
    --------------
    script_params: dict
        Script Parameters derived from User input
    data_dict: dict
        Data derived from tabbles {namespace:{key:['value1','value2', ...], key2: ...}, namespace2: ...}
    
    Returns:
    -------------
    new_tags: list
        simple list of strings ['tag1','tag2', ...]
    new_KVpairs_list: list
        list of list matching the needed format for annotating [[key1,value1],[key1,value2],[key2,value3],...]
    new_KVpairs_dict: dict
        matching the data_dict format 
    '''
    new_tags = []
    new_KVpairs_list = []  # a simple list of list, in the matching format for annotation
    new_KVpairs_dict = {}  # a dict of dicts of lists, matching the data_dict format from Tabbles

    # get lists/dicts for KV-pairs and Tags out of the data from Tabbles
    for namespace, key_values in data_dict.items():
        # TAGS 
        # Namespace should only be None for single tags, with a key "_workspace..."
        if script_params["Process_single_tags"]==True and namespace==None:
            for key, values in key_values.items():
                # double-check if it is really a singular Tabbles Tag, as only those
                # have "system" parent tags starting with "_..."
                if key.startswith("_"): 
                    for value in values:
                        new_tags.append(value)

        # KV-PAIRS
        # MapAnnotations will have a not None Namespace
        if not namespace==None:
            if len(getMaprNamespaces())==0:
            # create a list of lists, disregard Namespaces
                for key, values in key_values.items():
                    # double-check
                    assert key.startswith("_")==False, f"Problem with {namespace}:{key}:{values}"
                    for value in values:
                        # check if the KV-pair already exists (could be possible if 
                        # the same KV-pair exists in different NS)
                        if not [key,value] in new_KVpairs_list:
                            new_KVpairs_list.append([key,value])

            if len(getMaprNamespaces())>0:
            # create a dict of dicts of lists respecting Namespaces
                # check if specific parent Namespace-level tag in Tabbles exists, if not set it as OMERO default
                if namespace.startswith("_"):
                    namespace = DEFAULT_NAMESPACE
                else: namespace = transformToMaprNamespace(namespace)

                if namespace not in new_KVpairs_dict:
                    new_KVpairs_dict[namespace] = {}
                for key, values in key_values.items():
                    if key not in new_KVpairs_dict[namespace]:
                        new_KVpairs_dict[namespace][key] = []
                    for value in values:
                        if value not in new_KVpairs_dict[namespace][key]:
                            new_KVpairs_dict[namespace][key].append(value)
    
    return new_tags, new_KVpairs_list, new_KVpairs_dict


def annotateObject (conn, script_params, image, data_dict):
    """annotates any object with a given data dictionary from Tabbles as MapAnnotations or TagAnnotations

    Parameters:
    --------------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    script_params: dict
        Script Parameters derived from User input
    image: ``omero.model.ImageI`` object
        the image to be annotated
    data_dict: dict
        Data derived from tabbles {namespace:{key:['value1','value2', ...], key2: ...}, namespace2: ...}
    
    Returns:
    -------------
    counter_map_ann: int
        How many MapAnnotations got created (removed ones already subtracted)
    counter_tag_ann: int
        How many TagAnnotations got created (removed ones already subtracted)
    """
    
    counter_map_ann = 0
    counter_tag_ann = 0

    # get the data into fitting formats
    new_tags, new_KVpairs_list, new_KVpairs_dict = split_data(script_params, data_dict)
    

    # decide what to do with the new KV-Pairs/Tags        
    if script_params["What_to_do_with_existing_Annotations"]=="Overwrite":
        # TAGS
        # delete all old tags, check if the new Tags exists at all and create it if not, link all new Tags        
        if len(new_tags)>0:
            count_removed = remove_tag_annotations(conn,image)
            tag_dict = get_tag_dict(conn)
            counter = 0
            for tag_value in new_tags:
                # if the tag does not yet exist create it new
                if tag_value not in tag_dict:
                    tag_ann = omero.gateway.TagAnnotationWrapper(conn)
                    tag_ann.setValue(tag_value)
                    tag_ann.save()
                    tag_ann_id = tag_ann.getId()
                    image.linkAnnotation(tag_ann)
                    print(f"created new Tag '{tag_value}'.")
                    tag_dict[tag_value] = tag_ann_id
                    counter += 1
                # or get the existing one and link it
                else:
                    tag_ann = conn.getObject("TagAnnotation",tag_dict[tag_value])
                    image.linkAnnotation(tag_ann)
                    counter += 1
            counter_tag_ann = counter - count_removed
        
        # KV-PAIRS
        # without OMERO.Mapr
        if len(new_KVpairs_list)>0:
            assert len(getMaprNamespaces())==0, "something went wrong with OMERO.Mapr Parameter"
            namespace = DEFAULT_NAMESPACE
            # get all existing KV-pairs with the default Namespace
            existing_map_annotations_lists = []
            # check if KV-pairs with the default Namespace exist and retrieve them
            existing_map_annotations = get_existing_map_annotations(image)
            if len(existing_map_annotations)>0:
                if namespace in existing_map_annotations:
                    for key, values in existing_map_annotations[namespace].items():
                        for value in values:
                            existing_map_annotations_lists.append([key,value])
            # add the new KV-pairs to them
            combined_KV_list = new_KVpairs_list + existing_map_annotations_lists
            # and remove the old ones
            remove_map_annotations(conn, image, namespace)
            # then annotate the combined list
            map_ann = omero.gateway.MapAnnotationWrapper(conn)
            map_ann.setNs(namespace)
            map_ann.setValue(combined_KV_list) #expects a list of lists (of two strings, e.g. [[key1,value1][key1,value2]])
            map_ann.save()
            image.linkAnnotation(map_ann)
            counter_map_ann = counter_map_ann + len(new_KVpairs_list)
        
        # with OMERO.mapr
        if len(new_KVpairs_dict)>0:
            assert len(getMaprNamespaces())>0, "something went wrong with OMERO.Mapr Parameter"
            # check if Mapr Annotations exist that do not show up in 
            # the updated data, i.e. were deleted; if so, remove them
            existing_map_annotations = get_existing_map_annotations(image)
            deleted = 0
            added = 0
            mapr_namespaces = getMaprNamespaces()
            if len(existing_map_annotations)>0:
                for namespace in existing_map_annotations.keys():
                    if (namespace in mapr_namespaces) and (namespace not in new_KVpairs_dict):
                        deleted = deleted + len(existing_map_annotations[namespace])
                        remove_map_annotations(conn, image, namespace)

            for namespace, key_values in new_KVpairs_dict.items():
                if namespace in existing_map_annotations:
                    deleted = deleted + len(existing_map_annotations[namespace])
                remove_map_annotations(conn, image, namespace)
                map_ann = omero.gateway.MapAnnotationWrapper(conn)
                map_ann.setNs(namespace)
                kv_list = []
                for key,values in key_values.items():
                    for value in values:
                        kv_list.append([key,value])
                map_ann.setValue(kv_list)
                map_ann.save()
                image.linkAnnotation(map_ann)
                added = added + len(new_KVpairs_dict)
            counter_map_ann = added - deleted


    if script_params["What_to_do_with_existing_Annotations"]=="Append":
        # TAGS
        # check if the new Tags are already linked, if the Tag exists at all and create it if not
        if len(new_tags)>0:
            existing_tags = get_linked_tag_annotations(image)
            tag_dict = get_tag_dict(conn)
            for tag in new_tags:
                if tag not in existing_tags:
                    if tag not in tag_dict:
                        tag_ann = omero.gateway.TagAnnotationWrapper(conn)
                        tag_ann.setValue(tag)
                        tag_ann.save()
                        image.linkAnnotation(tag_ann)
                        print(f"created a new Tag '{tag}'.")
                        counter_tag_ann += 1
                    else:
                        tag_ann = conn.getObject("TagAnnotation",tag_dict[tag])
                        image.linkAnnotation(tag_ann)
                        counter_tag_ann += 1

        # KV-PAIRS
        # With OMERO.Mapr
        if len(new_KVpairs_dict)>0:
            assert len(getMaprNamespaces())>0, "something went wrong with OMERO.Mapr Parameter"
            existing_kvPairs = get_existing_map_annotations(image)
            # check if the new KV-pairs contain anything that is not already existing and
            # append it to the existing ones if so
            for namespace, key_values in new_KVpairs_dict.items():
                if namespace not in existing_kvPairs:
                    existing_kvPairs[namespace] = {}
                for key,values in key_values.items():
                    if key not in existing_kvPairs[namespace]:
                        existing_kvPairs[namespace][key] = []
                    for value in values:
                        if value not in existing_kvPairs[namespace][key]:
                            existing_kvPairs[namespace][key].append(value)
                            counter_map_ann += 1
            
            # delete the existing MapAnnoations and
            # annotate the combined dict
            for namespace, key_values in existing_kvPairs.items():
                remove_map_annotations(conn, image, namespace)
                map_ann = omero.gateway.MapAnnotationWrapper(conn)
                map_ann.setNs(namespace)
                kv_pairs_to_append = []
                for key, values in key_values.items():
                    for value in values:
                        kv_pairs_to_append.append([key,value])
                map_ann.setValue(kv_pairs_to_append)
                map_ann.save()
                image.linkAnnotation(map_ann)


        # Without OMERO.Mapr
        if len(new_KVpairs_list)>0:
            assert len(getMaprNamespaces())==0, "something went wrong with OMERO.Mapr Parameter"
            existing_kvPairs = get_existing_map_annotations(image)
            # change the format into a list of lists
            updated_list = []
            if DEFAULT_NAMESPACE in existing_kvPairs:
                for key, values in existing_kvPairs[DEFAULT_NAMESPACE].items():
                    for value in values:
                        updated_list.append([key,value])
            
            # check if the new list contains items that have to be appended to the existing KV-pairs
            for key_value in new_KVpairs_list:
                if key_value not in updated_list:
                    updated_list.append(key_value)
                    counter_map_ann += 1

            # remove the old MapAnnotations and annotate the updated list
            remove_map_annotations(conn, image, DEFAULT_NAMESPACE)
            map_ann = omero.gateway.MapAnnotationWrapper(conn)
            map_ann.setNs(DEFAULT_NAMESPACE)
            map_ann.setValue(updated_list)
            map_ann.save()
            image.linkAnnotation(map_ann)


    return counter_map_ann, counter_tag_ann

def tabbles_annotation(conn, script_params):
    '''Main function

    Parameters:
    --------------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    script_params: dict
        Script Parameters derived from User input
    
    Returns:
    -------------
    number_of_images: int
        Sum of annotated Images
    total_images: int
        Sum of all Images processed (annotated and un-annotated)
    sum_KVs: int
        Sum of added Key-Value Pairs
    sum_tags: int
        Sum of added Tags
    '''
    # get a list of all images
    images = getImages(conn, script_params)
    total_images = len(images)

    number_of_images = 0
    sum_KVs = 0
    sum_tags = 0
    
    last_path = ""
    for image in images:
        print("processing ",image.getName())
        import_path = image.getImportedImageFilePaths()['client_paths'][0]
        # check if ImportPath changed compared to last image to save a SQL query
        # this will probably only be relevant for HCS data or file formats acting as image containers
        if import_path != last_path:
            # get the data via SQL Query from the Tabbles Database
            data = getData(image, script_params)
            print("got data from SQL")
            print("data_dict: ",data)
        else: print("used data from last image")

        # for each image, pass the data from Tabbles, check the script paramters and
        # annotate accordingly MapAnnotations/TagAnnotations
        kvs_annotated, tags_annotated = annotateObject (conn, script_params, image, data)
        sum_KVs += kvs_annotated
        sum_tags += tags_annotated
        last_path = import_path
        if kvs_annotated!=0 or tags_annotated!=0: 
            number_of_images+=1
            print("succesfully annotated image")
            print("###########################")


    return number_of_images, total_images, sum_KVs, sum_tags
   

def run_script():

    data_types = [rstring('Project'), rstring('Dataset'), rstring('Image')]
    existing_kv = [rstring('Append'), rstring('Overwrite')]
    tabbles_database = [rstring('tabbles_production'), rstring('tabbles_dev')]
    client = scripts.client(
        'Get_Annotations_from_Tabbles',
        """
    This script connects to the Tabbles Database and gets Tabbles-Tags for the original files of the selected Images.
    Then it converts them to Key-Value pairs and Tags in OMERO.
        """,
        scripts.String(
            "Data_Type", optional=False, grouping="1",
            description="Choose source of images",
            values=data_types, default="Dataset"),

        scripts.List(
            "IDs", optional=False, grouping="2",
            description="single ID or comma separated list of IDs").ofType(rlong(0)),

        scripts.Bool(
            "Process_single_tags", optional=True, grouping="4",
            description="Allows to create OMERO Tags from single Tabble Tags without Parents",
            default=True),

        scripts.String(
            "What_to_do_with_existing_Annotations", optional=False, grouping="5",
            description="If Key-Value pairs (with this Namespace) exist, the"
            " existing KV-pairs can be removed and only the new ones get added with the option 'Overwrite'.\n"
            "The option 'Append' will compare existing KV-pairs (of a Namespace) with the set of proposed new ones and append only the non-existing new KV-pairs.\n"
            "The same logic will apply for Tags.",
            values=existing_kv, default="Overwrite"),

        scripts.String(
            "Tabbles_Database", optional=False, grouping="6",
            description="Choose which Tabbles Database you are on. Can be checked in\n" 
            "Tabbles under Help > Show current server and user",
            values=tabbles_database, default="tabbles_production"),

        authors=["Jens Wendt"],
        institutions=["Imaging Network, Uni Muenster"],
        contact="https://forum.image.sc/tag/omero"
    )

    try:
        # process the list of args above.
        script_params = {}
        for key in client.getInputKeys():
            if client.getInput(key):
                script_params[key] = client.getInput(key, unwrap=True)

        # wrap client to use the Blitz Gateway
        conn = BlitzGateway(client_obj=client)
        
        # get login parameters for the Microsoft SQL Server from a .json on the OMERO server
        global DRIVER,SERVER,DATABASE,USERNAME,PWD
        with open('/opt/omero/MSSQL_login.json', 'r') as fp:
            data = json.load(fp)
        DRIVER = data["DRIVER"]
        SERVER = data["SERVER"]
        DATABASE = data["DATABASE"]
        USERNAME = data["UID"]
        PWD = data["PWD"]

        #################
        # MAIN FUNCTION #
        number_of_images, total_images, sum_KVs, sum_tags = tabbles_annotation(conn, script_params)
        #################
        
        # 4 cases to display the grammatically correct message for each case
        if sum_tags>=0 and sum_KVs>=0:
            message = f"Annotated {number_of_images}/{total_images} images. Appended {sum_KVs} total Key-Value pairs and {sum_tags} total Tags."
        elif sum_tags>=0 and sum_KVs<0:
            message = f"Annotated {number_of_images}/{total_images} images. Removed {abs(sum_KVs)} total Key-Value pairs and appended {sum_tags} total Tags."
        elif sum_tags<0 and sum_KVs>=0:
            message = f"Annotated {number_of_images}/{total_images} images. Appended {sum_KVs} total Key-Value pairs and removed {abs(sum_tags)} total Tags."
        elif sum_tags<0 and sum_KVs<0:
            message = f"Annotated {number_of_images}/{total_images} images. Removed {abs(sum_KVs)} total Key-Value pairs and removed {abs(sum_tags)} total Tags."
        
        client.setOutput("Message", rstring(message))

    finally:
        client.closeSession()

if __name__ == "__main__":
    run_script()