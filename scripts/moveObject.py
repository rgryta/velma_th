#!/usr/bin/env python2
import roslib; roslib.load_manifest('velma_task_cs_ros_interface')
import rospy
import copy
import time
import numpy as np

from velma_common import *
from rcprg_planner import *
import PyKDL
from threading import Thread

from rcprg_ros_utils import MarkerPublisher, exitError

from moveit_msgs.msg import AttachedCollisionObject, CollisionObject
from shape_msgs.msg import SolidPrimitive

from geometry_msgs.msg import Pose
from visualization_msgs.msg import Marker
import tf_conversions.posemath as pm

class MarkerPublisherThread:
    def threaded_function(self, obj):
        pub = MarkerPublisher("attached_objects")
        while not self.stop_thread:
            pub.publishSinglePointMarker(PyKDL.Vector(), 1, r=1, g=0, b=0, a=1, namespace='default', frame_id=obj.link_name, m_type=Marker.CYLINDER, scale=Vector3(0.02, 0.02, 1.0), T=pm.fromMsg(obj.object.primitive_poses[0]))
            try:
                rospy.sleep(0.1)
            except:
                break

        try:
            pub.eraseMarkers(0, 10, namespace='default')
            rospy.sleep(0.5)
        except:
            pass

    def __init__(self, obj):
        self.thread = Thread(target = self.threaded_function, args = (obj, ))

    def start(self):
        self.stop_thread = False
        self.thread.start()

    def stop(self):
        self.stop_thread = True
        self.thread.join()


 # define a function for frequently used routine in this test
def planAndExecute(velma, q_dest, object1):
    # type: (object, object, object) -> object
    print "Moving to valid position, using planned trajectory."
    goal_constraint = qMapToConstraints(q_dest, 0.01, group=velma.getJointGroup("impedance_joints"))
    for i in range(10):
        rospy.sleep(0.5)
        js = velma.getLastJointState()
        print "Planning (try", i, ")..."
        if object1==None:
            traj = p.plan(js[1], [goal_constraint], "impedance_joints", max_velocity_scaling_factor=0.15,
                          planner_id="RRTConnect")
        else:
            traj = p.plan(js[1], [goal_constraint], "impedance_joints", max_velocity_scaling_factor=0.15,
                          planner_id="RRTConnect", attached_collision_objects=[object1])
        if traj == None:
            continue
        print "Executing trajectory..."
        if not velma.moveJointTraj(traj, start_time=0.5):
            exitError(5)
        if velma.waitForJoint() == 0:
            break      
        else:
            print "The trajectory could not be completed, retrying..."
            continue
    rospy.sleep(0.5)
    js = velma.getLastJointState()
    if not isConfigurationClose(q_dest, js[1]):
        exitError(6)  

def moveInCartImpMode(velma, T_B_dest):
    if not velma.moveCartImpRight([T_B_dest], [5.0], None, None, None, None, PyKDL.Wrench(PyKDL.Vector(5,5,5), PyKDL.Vector(5,5,5)), start_time=0.5):
        exitError(8)
    rospy.sleep(0.5)
    if velma.waitForEffectorRight() != 0:
        exitError(9)
    rospy.sleep(0.5)

def moveForEquilibrium(velma):
    arm_frame = velma.getTf("B", "Gr")
    T_Wr_Gr = velma.getTf("Wr", "Gr")
    if not velma.moveCartImpRight([arm_frame], [0.1], [T_Wr_Gr], [0.1], None, None, PyKDL.Wrench(PyKDL.Vector(5,5,5), PyKDL.Vector(5,5,5)), start_time=0.5):
        exitError(18)
    rospy.sleep(0.5)
    if velma.waitForEffectorRight() != 0:
        exitError(19)
    print "The right tool is now in 'grip' pose"
    rospy.sleep(0.5)

def prepareForGrip(velma, torso_angle):
    executable_q_map = copy.deepcopy(q_map_acquiring)
    executable_q_map['torso_0_joint'] = torso_angle
    planAndExecute(velma, executable_q_map, None)

def grabWithRightHand(velma):
    dest_q = [76.0/180.0*math.pi, 76.0/180.0*math.pi, 76.0/180.0*math.pi, 0]
    velma.moveHandRight(dest_q, [1,1,1,1], [2000,2000,2000,2000], 800, hold=True)
    if velma.waitForHandRight() != 0:
        exitError(10)
    rospy.sleep(0.5)
    if isHandConfigurationClose( velma.getHandRightCurrentConfiguration(), dest_q):
        print "Couldn't grab"
        exitError(11)
    rospy.sleep(0.5)

def moveToPositionZero(velma):
    print "Moving to position 0"
    print "Switch to jnt_imp mode."
    velma.moveJointImpToCurrentPos(start_time=0.5)
    velma.waitForJoint()

    print "Moving body to position 0"
    planAndExecute(velma, q_map_starting, None)

    print "Moving head to position: 0"
    q_dest = (0,0)
    velma.moveHead(q_dest, 3.0, start_time=0.5)
    if velma.waitForHead() != 0:
        exitError(5)
    rospy.sleep(0.5)
    if not isHeadConfigurationClose( velma.getHeadCurrentConfiguration(), q_dest, 0.1 ):
        exitError(6)

def findCanOnTable(table_tf, cafe_tf, can_tf):
    [t0_x, t0_y, t0_z] = table_tf.p
    [t1_x, t1_y, t1_z] = cafe_tf.p
    [c_x, c_y, c_z] = can_tf.p

    can_to_t0 = (c_x - t0_x)**2 + (c_y - t0_y)**2 + (c_z - t0_z)**2
    can_to_t1 = (c_x - t1_x)**2 + (c_y - t1_y)**2 + (c_z - t1_z)**2

    return "table" if can_to_t0 < can_to_t1 else "cafe"

def switchToJntMode(velma):
    velma.moveJointImpToCurrentPos(start_time=0.2)
    error = velma.waitForJoint()
    if error != 0:
        print "The action should have ended without error, but the error code is", error
        exitError(3)
 
    rospy.sleep(0.5)
    diag = velma.getCoreCsDiag()
    if not diag.inStateJntImp():
        print "The core_cs should be in jnt_imp state, but it is not" 
        exitError(3)

def switchToCartMode(velma):
    if not velma.moveCartImpRightCurrentPos(start_time=0.2):
        print "Cannot moveCartImpRightCurrentPos"
        exitError(9)

    if velma.waitForEffectorRight() != 0:
        print "waitForEffectorright error"
        exitError(8)

    if not velma.moveCartImpLeftCurrentPos(start_time=0.2):
        print "Cannot moveCartImpLeftCurrentPos"
        exitError(9)

    if velma.waitForEffectorLeft() != 0:
        print "waitForEffectorLeft error"
        exitError(8)

    rospy.sleep(0.5) 
    diag = velma.getCoreCsDiag()
    if not diag.inStateCartImp():
        print "The core_cs should be in cart_imp state, but it is not"
        exitError(3)

def openRightHand(velma):
    dest_q = [0, 0, 0, 0]
    velma.moveHandRight(dest_q, [1,1,1,1], [2000,2000,2000,2000], 1000, hold=True)
    if velma.waitForHandRight() != 0:
        exitError(10)
    rospy.sleep(1)
    if not isHandConfigurationClose( velma.getHandRightCurrentConfiguration(), dest_q):
        exitError(11)

def normalizeTorsoAngle(torso_angle):
    if torso_angle>math.pi/2:
        return math.pi/2-0.1
    elif torso_angle<-math.pi/2:
        return -math.pi/2+0.1
    else:
        return torso_angle

def getAngleFromRot(rotation, rotAngle):
    if rotAngle.lower() in ['r']:
        return rotation.GetRPY()[0]
    elif rotAngle.lower() in ['p']:
        return rotation.GetRPY()[1]
    elif rotAngle.lower() in ['y']:
        return rotation.GetRPY()[2]

def getAdjCanPos(wrPos, canPos, r):
    #gets x,y Can position but moved r distance in favor of wrench position
    dx = wrPos[0]-canPos[0]
    dy = wrPos[1]-canPos[1]
    l = math.sqrt(math.pow(dx,2)+math.pow(dy,2))
    newPos = PyKDL.Vector(canPos[0]+(r/l)*dx,canPos[1]+(r/l)*dy,0)
    return newPos

def adjustCornerPos(x, y, cx, cy, angle):
    x1 = x*math.cos(angle) - y*math.sin(angle) + cx
    y1 = x*math.sin(angle) + y*math.cos(angle) + cy
    return [x1, y1]

def getCorners(tPos, width, length, angle):
    cx = tPos[0]
    cy = tPos[1]
    x1 = width/2
    y1 = length/2
    c1 = adjustCornerPos(x1, y1, cx, cy, angle)
    x1 = width/2
    y1 = -length/2
    c2 = adjustCornerPos(x1, y1, cx, cy, angle)
    x1 = -width/2
    y1 = -length/2
    c3 = adjustCornerPos(x1, y1, cx, cy, angle)
    x1 = -width/2
    y1 = length/2
    c4 = adjustCornerPos(x1, y1, cx, cy, angle)
    #c1>c2>c3>c4>c1
    return [c1, c2, c3, c4]

def getClosestPointToLine(segPos, wrPos):
    xDelta = segPos[1][0] - segPos[0][0]
    yDelta = segPos[1][1] - segPos[0][1]
    l = ((wrPos[0] - segPos[0][0]) * xDelta + (wrPos[1] - segPos[0][1]) * yDelta) / (xDelta * xDelta + yDelta * yDelta)
    if l <= 0:
        [xc, yc] = segPos[0]
    elif l >= 1:
        [xc, yc] = segPos[1]
    else:
        xc = segPos[0][0] + l*xDelta
        yc = segPos[0][1] + l*yDelta
    return [xc, yc]


def getDistance(x, y, xc, yc):
    dx = math.pow(x-xc,2)
    dy = math.pow(y-yc,2)
    return math.sqrt(dx+dy)

def getClosestPoint(wrPos, tFrame, width, length):
    x = tFrame.p[0]
    y = tFrame.p[1]
    angle=getAngleFromRot(tFrame.M,'y')
    xc = wrPos[0]
    yc = wrPos[1]
    [c1, c2, c3, c4] = getCorners([x, y], width, length, angle)
    finalX = -1
    finalY = -1
    finalD = -1
    segments = [[c1, c2],[c2, c3],[c3, c4],[c4, c1]]
    for segment in segments:
        [xf, yf] = getClosestPointToLine(segment, [xc, yc])
        dist = getDistance(xf, yf, xc, yc)
        if finalD == -1 or dist<finalD:
            finalX = xf
            finalY = yf
            finalD = dist
    return [finalX, finalY]

if __name__ == "__main__":
    # define some configurations
    q_map_starting = {'torso_0_joint':0,
        'right_arm_0_joint':-0.3,   'left_arm_0_joint':0.3,
        'right_arm_1_joint':-1.8,   'left_arm_1_joint':1.8,
        'right_arm_2_joint':1.25,   'left_arm_2_joint':-1.25,
        'right_arm_3_joint':0.85,   'left_arm_3_joint':-0.85,
        'right_arm_4_joint':0,      'left_arm_4_joint':0,
        'right_arm_5_joint':-0.5,   'left_arm_5_joint':0.5,
        'right_arm_6_joint':0,      'left_arm_6_joint':0 }

    q_map_acquiring = {'torso_0_joint': 0, 
        'right_arm_0_joint':1,   'left_arm_0_joint':0.3,
        'right_arm_1_joint':-1.80,  'left_arm_1_joint':1.8,
        'right_arm_2_joint':1.8,   'left_arm_2_joint':-1.25,
        'right_arm_3_joint':2,   'left_arm_3_joint':-0.85,
        'right_arm_4_joint':0.0,   'left_arm_4_joint':0,
        'right_arm_5_joint':-0.5,  'left_arm_5_joint':0.5,
        'right_arm_6_joint':0.0,  'left_arm_6_joint':0 }

    #standard initialization
    rospy.init_node('thesis')
    rospy.sleep(0.5)

    print "Initializing robot..."
    velma = VelmaInterface()
    if not velma.waitForInit(timeout_s=10.0):
        print "Could not initialize VelmaInterface\n"
        exitError(1)
    
    if velma.enableMotors() != 0:
        exitError(14)

    diag = velma.getCoreCsDiag()
    if not diag.motorsReady():
        print "Motors must be homed and ready to use for this test."
        exitError(1)

    #adding octomap to planner
    p = Planner(velma.maxJointTrajLen())
    if not p.waitForInit():
        print "could not initialize Planner"
        exitError(2)
    oml = OctomapListener("/octomap_binary")
    rospy.sleep(1.0)
    octomap = oml.getOctomap(timeout_s=5.0)
    p.processWorld(octomap)

    print "Switching to jnt_mode..."
    switchToJntMode(velma)

    print "Moving to position zero"
    #moveToPositionZero(velma)

    print "Start"
    start = time.time()

    print "Rotating robot..."
    # can position
    T_Wo_Can = velma.getTf("Wo", "beer")
    T_Wo_Table_0 = velma.getTf("Wo", "table")
    T_Wo_Table_1 = velma.getTf("Wo", "cafe")

    target_table = findCanOnTable(T_Wo_Table_0, T_Wo_Table_1, T_Wo_Can) # na ktorym stoliku znajduje sie puszka

    Can_x = T_Wo_Can.p[0]   
    Can_y = T_Wo_Can.p[1]
    Can_z = T_Wo_Can.p[2]

    torso_angle = normalizeTorsoAngle(math.atan2(Can_y, Can_x))
    prepareForGrip(velma, torso_angle)

    switchToCartMode(velma)

    print "Moving the right tool and equilibrium pose from 'wrist' to 'grip' frame..."
    arm_aq = velma.getTf("Wo", "Gr") #save returning point
    moveForEquilibrium(velma)

    print "Moving grip to can..."
    pos1 = velma.getTf("Wo", "Gr")
    pos2 = velma.getTf("Wo", "beer")
    vector = pos2.p - pos1.p
    xAngle = math.atan2(vector[1],vector[0])
    move_rotation = PyKDL.Rotation.RPY(-xAngle,math.pi/2, 0)

    move_vector = PyKDL.Vector(arm_aq.p[0], arm_aq.p[1], T_Wo_Can.p[2]+0.01)
    to_can_frame = PyKDL.Frame(move_rotation, move_vector)
    moveInCartImpMode(velma, to_can_frame)

    move_vector = getAdjCanPos(arm_aq.p,T_Wo_Can.p, 0.018)+PyKDL.Vector(0, 0, T_Wo_Can.p[2]+0.01)
    to_can_frame = PyKDL.Frame(move_rotation, move_vector)
    moveInCartImpMode(velma, to_can_frame)

    print "Grabbing the can..."
    grabWithRightHand(velma)

    # for more details refer to ROS docs for moveit_msgs/AttachedCollisionObject
    object1 = AttachedCollisionObject()
    object1.link_name = "right_HandGripLink"
    object1.object.header.frame_id = "right_HandGripLink"
    object1.object.id = "object1"
    object1_prim = SolidPrimitive()
    object1_prim.type = SolidPrimitive.CYLINDER
    object1_prim.dimensions=[None, None]    # set initial size of the list to 2
    object1_prim.dimensions[SolidPrimitive.CYLINDER_HEIGHT] = 0.25
    object1_prim.dimensions[SolidPrimitive.CYLINDER_RADIUS] = 0.06
    object1_pose = pm.toMsg(PyKDL.Frame(PyKDL.Rotation.RotY(math.pi/2),PyKDL.Vector(0.12,0,0)))
    object1.object.primitives.append(object1_prim)
    object1.object.primitive_poses.append(object1_pose)
    object1.object.operation = CollisionObject.ADD
    object1.touch_links = ['right_HandPalmLink',
        'right_HandFingerOneKnuckleOneLink',
        'right_HandFingerOneKnuckleTwoLink',
        'right_HandFingerOneKnuckleThreeLink',
        'right_HandFingerTwoKnuckleOneLink',
        'right_HandFingerTwoKnuckleTwoLink',
        'right_HandFingerTwoKnuckleThreeLink',
        'right_HandFingerThreeKnuckleOneLink',
        'right_HandFingerThreeKnuckleTwoLink',
        'right_HandFingerThreeKnuckleThreeLink']
    print "Publishing the attached object marker on topic /attached_objects"
    pub = MarkerPublisherThread(object1)
    pub.start()

    print "Moving right gripper up..."
    arm_frame = PyKDL.Frame(move_rotation,arm_aq.p)
    moveInCartImpMode(velma, arm_frame)

    print "Switching to jnt_mode..."
    switchToJntMode(velma)
    if target_table == "table":
        target_table = "cafe"
        print "go to: cafe"
    else:
        target_table = "table"
        print "go to: table"
    T_Wo_Dest = velma.getTf("Wo", target_table)
    Target_x = T_Wo_Dest.p[0]
    Target_y = T_Wo_Dest.p[1]

    torso_angle = normalizeTorsoAngle(math.atan2(Target_y, Target_x))

    stateUpdate = velma.getLastJointState()[1] #(genpy.Time, {lastState})
    stateUpdate['torso_0_joint'] = torso_angle
    for joint in q_map_acquiring:
        q_map_acquiring[joint] = round(stateUpdate[joint],2)
    print 'To starting'
    planAndExecute(velma,q_map_starting, object1)
    planAndExecute(velma,q_map_acquiring, object1)

    print "Move to target table"
    switchToCartMode(velma)
    T_Wo_table = velma.getTf("Wo", target_table)    #calculating position for can placement
    Wr_pos=velma.getTf("Wo", "Gr") #save reference frame
    [xf, yf] = getClosestPoint(Wr_pos.p,T_Wo_table,1.3,0.6)
    table_height=1.2
    zf = T_Wo_table.p[2]+table_height

    move_rotation=velma.getTf("B", "Gr") #save reference frame

    moveForEquilibrium(velma)

    print "Start gripper move"
    place_can_frame = PyKDL.Frame(move_rotation.M, PyKDL.Vector(move_rotation.p[0], move_rotation.p[1], zf+0.1))  #starting frame for can placement
    moveInCartImpMode(velma, place_can_frame)
    place_can_frame = PyKDL.Frame(move_rotation.M, PyKDL.Vector(xf, yf, zf+0.1))
    moveInCartImpMode(velma, place_can_frame)
    place_can_frame = PyKDL.Frame(move_rotation.M, PyKDL.Vector(xf, yf, zf))
    moveInCartImpMode(velma, place_can_frame)

    print "release object"
    openRightHand(velma)

    pub.stop()
    print "gripper move back"
    moveInCartImpMode(velma, move_rotation)


    print "return to start position"
    print "Switching to jnt_mode..."
    switchToJntMode(velma)
    moveToPositionZero(velma)
    end = time.time()
    print(end - start)

print "end"
