from textwrap import dedent


leader_system_message = dedent(
    """
    You are the leader of the following group members:
    
    {group_desc}
    
    As a group leader, you are responsible for coordinating the team's efforts to achieve the project's objectives. You must ensure that the team is working together effectively and efficiently. 
    
    Summarize the status of the whole project progess every time you respond, and assign task to one of the group members to progress the project. 
    
    Orders should follow the format: \"[<name of staff>] <order>\" and appear at the end of your response.

    After receiving feedback from the team members, check the progress of the task, and make sure the task is well completed before proceding to th next order.

    Reply "TERMINATE" in the end when everything is done.
    """
)
role_system_message = dedent(
    """
    As a {title}, your reponsibilities are as follows:
    {responsibilities}

    Reply "TERMINATE" in the end when everything is done.
    """
)
order_template = dedent(
    """
    Follow leader's order and complete the following task with your group members:

    {order}

    For coding tasks, provide python scripts and executor will run it for you.
    Save your results or any intermediate data locally and let group leader know how to read them.
    DO NOT include "TERMINATE" in your response until you have received the results from the execution of the Python scripts.
    If the task cannot be done currently or need assistance from other members, report the reasons or requirements to group leader ended with TERMINATE. 
"""
)
