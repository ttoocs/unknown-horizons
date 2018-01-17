pipeline{
  agent any

  stages{
    stage('Fife'){
      steps {
        sh 'echo TODO'
        sh 'python3 -c "from fife import fife; print(fife.getVersion())"'
      }
    }
    stage('Non-GUI-tests'){
      steps {
        sh 'isort -c -rc horizons tests *.py'
        sh 'pycodestyle horizons tests *.py development'
        sh 'COVERAGE_FILE=.coverage.nongui pytest --verbose --cov --cov-report= -rs'
      }
    }
    stage('GUI-tests'){
      steps {
        sh 'Xvfb :99 -ac -screen 0 1290x1024x16 && PID=$! ; RUNCOV=1 pytest --gui-tests tests/gui --verbose --cov --cov-report= -rs ; kill -9 $PID;'
      }
    }
  }
}
        
