class STEPPER
{
  public:
    byte DirPin, PulPin, EnablePin;
    unsigned long StepTime = 1000, LastStepSt = 0;
    long CurrentStep = 0, TargetStep = 0;

    STEPPER(byte dir, byte pul, byte en)
    {
      DirPin = dir;
      PulPin = pul;
      EnablePin = en;
      pinMode(DirPin, OUTPUT);
      pinMode(PulPin, OUTPUT);
      pinMode(EnablePin, OUTPUT);

      digitalWrite(DirPin, 0);
      digitalWrite(PulPin, 0);
      digitalWrite(EnablePin, 0);
    }

    bool IsRunToTarget()
    {
      return TargetStep == CurrentStep;
    }

    bool CanRun()
    {
      return micros() - LastStepSt >= StepTime;
    }

    bool RunTo(long target)
    {
      TargetStep = target;
      if (IsRunToTarget() == false)
      {
        if (CanRun())
        {
          runStep(CurrentStep < target);
        }
      }

      return IsRunToTarget();
    }

    bool RunTo(long target, unsigned long stepTime)
    {
      TargetStep = target;
      StepTime = stepTime;
      if (IsRunToTarget() == false)
      {
        if (CanRun())
        {
          runStep(CurrentStep < target);
        }
      }

      return IsRunToTarget();
    }

    void RunCycle(bool dir,  unsigned long stepTime)
    {
      StepTime = stepTime;
      if (CanRun())
      {
        runStep( dir);
      }
    }

  private:
    void runStep(bool dir)
    {
      LastStepSt = micros();
      digitalWrite(DirPin, dir);
      digitalWrite(PulPin, 1);
      delayMicroseconds(10);
      digitalWrite(PulPin, 0);
      CurrentStep += (dir ? 1 : -1);
    }
};

STEPPER  MyStepperA(2, 3, 4);
STEPPER  MyStepperB(5, 6, 7);

void setup()
{
  while (1)
  {
    MyStepperA.RunTo(2000, 600);
    MyStepperB.RunTo(2000);

    if (MyStepperA.IsRunToTarget() && MyStepperB.IsRunToTarget())
      break;
  }
  delay(2000);

  while (1)
  {
    MyStepperA.RunTo(-2000, 1000);
    MyStepperB.RunTo(-2000, 600);

    if (MyStepperA.IsRunToTarget() && MyStepperB.IsRunToTarget())
      break;
  }
  delay(2000);
}

void loop()
{
  MyStepperA. RunCycle(1, 1600);
  MyStepperB. RunCycle(0, 600);
}





