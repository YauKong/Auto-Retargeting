import maya.cmds as cmds
import json



'''
Forming the full name of the source and target joint.

Args:
    str namespace: The Naming space (before the joint name)
    str obj: The name of the joint (both target and source)

Return:
    obj: The name of the joint when there is no namespace
    full_name: The name of the joint with the namespace.
    
''' 

def apply_retargeting(target_namespace = '', source_namespace = '',mappings = None,config_file=None, neutral_frame=-1):

    def get_full_name(obj, namespace = None):
        if namespace:
            full_name = f'{namespace}:{obj}'
            return full_name
        else:
            return obj


    print(f"Target {target_namespace}\tsource {source_namespace}")

    with open(config_file,"r") as file:
        mappings = json.load(file)

    all_constraint_object = []
    moveable_objects = []
    rotate_objects = []
    
    r_attrs = ['rx','ry','rz']
    t_attrs = ['tx','ty','tz']
    
    all_attrs = ['tx','ty','tz','rx','ry','rz']
    all_frames = set()
    cmds.currentTime(neutral_frame)

    #print(mappings)
    for mapping in mappings:
        source_name = get_full_name(mapping.get("source_joint"),source_namespace)
        target_name = get_full_name(mapping.get("target_control"),target_namespace)
        move_able = mapping.get("move_able")

        orient_constraint = cmds.orientConstraint(source_name,target_name, mo = True)[0]
        all_constraint_object.append(orient_constraint)
        

        if move_able:
            point_constraint = cmds.pointConstraint(source_name,target_name,mo = False)[0]
            #print(parent_constraint)
            #all_constraint_object.append(parent_constraint)
            all_constraint_object.append(point_constraint)
            moveable_objects.append(target_name)

        else:
            rotate_objects.append(target_name)

        attr_list = all_attrs
        if not move_able:
            attr_list = r_attrs
        
        print(attr_list)

        for attr in attr_list:
            attr_name = f'{source_name}.{attr}'
            frame = cmds.keyframe(attr_name, query = True, timeChange = True)
            frame = [] if frame is None else frame
            all_frames.update(frame)

    print(all_constraint_object)
    
    all_value = {}
    for frame in sorted(all_frames):
        cmds.currentTime(frame)
        all_value[frame] = {}
        for obj in rotate_objects:
            all_value[frame][obj] = {}
            for attr in r_attrs:
                all_value[frame][obj][attr] = cmds.getAttr(f'{obj}.{attr}')

        for obj in moveable_objects:
            all_value[frame][obj] = {}
            for attr in all_attrs:
                all_value[frame][obj][attr] = cmds.getAttr(f'{obj}.{attr}')
        
    cmds.delete(all_constraint_object)
    print(all_value)
    
    
    for current_frame, frame_value in all_value.items():
        for obj, attributes in frame_value.items():
            for attri_name, attr in attributes.items():
                cmds.setKeyframe(f'{obj}.{attri_name}',value = attr,time = current_frame)
    

    for mapping in mappings:
        target_control = get_full_name(mapping.get('target_control'), target_namespace)
        anim_curves = cmds.listConnections(target_control, type='animCurve') or []
        if anim_curves:
            cmds.filterCurve(anim_curves, filter="euler")
    


if __name__ == '__main__':
    # Example usage
    config_file = 'C:/Users/Administrator/Documents/retarget/config.json'
    target_namespace = 'Fight'
    source_namespace = ''
    apply_retargeting(target_namespace, source_namespace, config_file)