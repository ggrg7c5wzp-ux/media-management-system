VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Report_rptSortingReport"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Compare Database

Option Explicit

Private Sub ApplyGridLinesToReport()

    Dim ctl As Control

    ' Detail section: make each text box look like a cell in a grid
    For Each ctl In Me.Section(acDetail).Controls
        If ctl.ControlType = acTextBox Then
            ctl.BorderStyle = 1      ' Solid
            ctl.BorderWidth = 1      ' 1 pt (you can try 2 if you want thicker)
            ctl.BorderColor = vbBlack
        End If
    Next ctl

    ' Optional: do the same for the header so column headers line up
    On Error Resume Next
    For Each ctl In Me.Section(acPageHeader).Controls
        If ctl.ControlType = acTextBox Or ctl.ControlType = acLabel Then
            ctl.BorderStyle = 1
            ctl.BorderWidth = 1
            ctl.BorderColor = vbBlack
        End If
    Next ctl
    On Error GoTo 0

End Sub
Private Sub Report_Load()
    Call ApplyGridLinesToReport
End Sub

