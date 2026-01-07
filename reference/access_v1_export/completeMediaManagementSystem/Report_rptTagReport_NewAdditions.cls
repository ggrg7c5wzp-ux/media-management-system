VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Report_rptTagReport_NewAdditions"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Compare Database
Option Explicit

Private mRow As Long

Private Sub Detail_Format(Cancel As Integer, FormatCount As Integer)

    ' Increment ONCE per record print cycle
    If FormatCount = 1 Then
        mRow = mRow + 1
    End If

    ' Stripe the rectangle behind the row
    If (mRow Mod 2) = 0 Then
        Me.rctStripe.BackColor = RGB(245, 245, 245)  ' light gray
    Else
        Me.rctStripe.BackColor = vbWhite
    End If

    ' Optional: hide TagNote when blank (only if you want)
    'Me.txtTagNote.Visible = (Len(Nz(Me.txtTagNote, "")) > 0)

End Sub


Private Sub Report_Open(Cancel As Integer)
    mRow = 0
End Sub

